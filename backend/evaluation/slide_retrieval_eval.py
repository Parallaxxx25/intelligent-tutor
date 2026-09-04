"""
Intrinsic retrieval evaluation for the slide-material RAG layer
(backend/rag/slide_retriever.py).

Answers: does search_slides() actually find the right slide? Compares four
retrieval arms over the same 40 gold-labeled queries
(backend/evaluation/data/slide_rag_eval.csv):

    dense       -- Chroma dense similarity only
    bm25        -- lexical BM25 only
    hybrid      -- RRF fusion of the two (search_slides, no error_type boost)
    hybrid_boost-- RRF fusion + the *= 1.5 error_type soft boost search_slides
                   applies in production

No LLM calls, no API cost, fully deterministic given the persisted index —
run this before spending judge tokens in run_slide_ablation.py: if hybrid
doesn't beat both single-mode arms here, the gold labels or the query
template have drifted from production, and the extrinsic numbers downstream
won't mean anything either.

Usage:
    python -m backend.evaluation.slide_retrieval_eval
    python -m backend.evaluation.slide_retrieval_eval --k 1 3 5
    python -m backend.evaluation.slide_retrieval_eval --dataset-csv path.csv
"""

from __future__ import annotations

import sys

# Windows consoles default to cp1252, which chokes on "—" and Thai text
# in the report strings this module prints.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import math
import random
from dataclasses import dataclass

from backend.evaluation.eval_dataset import EvalSample, load_eval_dataset_from_csv

DEFAULT_DATASET_CSV = "backend/evaluation/data/slide_rag_eval.csv"
ARMS = ("dense", "bm25", "hybrid", "hybrid_boost")


# ---------------------------------------------------------------------------
# Metrics (binary relevance, gold = set of "lab:page" strings per sample)
# ---------------------------------------------------------------------------

def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    """|top-k ∩ gold| / |gold|. Undefined (None) when gold is empty."""
    if not gold:
        return None  # type: ignore[return-value]
    hit = len(set(ranked[:k]) & gold)
    return hit / len(gold)


def mrr(ranked: list[str], gold: set[str]) -> float:
    """Reciprocal rank of the first relevant item; 0.0 if none found."""
    if not gold:
        return None  # type: ignore[return-value]
    for i, doc_id in enumerate(ranked, start=1):
        if doc_id in gold:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    """Binary-relevance nDCG@k."""
    if not gold:
        return None  # type: ignore[return-value]
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in gold)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / idcg if idcg > 0 else 0.0


def bootstrap_ci(values: list[float], n_resamples: int = 10_000, seed: int = 0) -> tuple[float, float, float]:
    """(mean, lo95, hi95) via percentile bootstrap. stdlib random only."""
    if not values:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_resamples)]
    hi = means[int(0.975 * n_resamples) - 1]
    return (sum(values) / n, lo, hi)


# ---------------------------------------------------------------------------
# Retrieval arms
# ---------------------------------------------------------------------------

def _rag_query(sample: EvalSample) -> str:
    """Must match supervisor.py's rag_query template exactly (see
    diagnose_and_hint) -- these numbers describe a retriever nobody runs
    otherwise."""
    return (
        f"SQL error: {sample.error_type}. "
        f"Student query: {sample.student_query}. "
        f"Error: {sample.error_message}"
    )


def _doc_id_to_key(doc_id: str, by_id: dict[str, dict]) -> str:
    meta = by_id.get(doc_id, {}).get("metadata", {})
    return f"{meta.get('lab_no', '?')}:{meta.get('page', '?')}"


@dataclass
class ArmResult:
    sample_id: str
    arm: str
    error_type: str
    lab_no: int
    recall: dict[int, float]
    mrr: float
    ndcg: dict[int, float]
    lab_recall_at5: float  # coarser signal: did it find the right *deck*, even on the wrong slide?


def run_retrieval_eval(
    samples: list[EvalSample], k_values: tuple[int, ...] = (1, 3, 5)
) -> list[ArmResult]:
    from backend.rag import slide_retriever as sr

    if sr.get_slide_collection() is None:
        sr.initialize_slide_kb()

    by_id = {d["id"]: d for d in sr._bm25_docs}  # noqa: SLF001 -- eval reads internal index directly
    fetch_k = max(k_values)
    where = {"category": "query"}
    allowed_ids = {d["id"] for d in sr._bm25_docs if d["metadata"].get("category") == "query"}  # noqa: SLF001

    results: list[ArmResult] = []
    skipped_no_gold = 0

    for sample in samples:
        gold = set(sample.gold_slides)
        if not gold:
            skipped_no_gold += 1
            continue

        query = _rag_query(sample)
        lab_no = int(sample.gold_slides[0].split(":")[0])

        rankings = {
            "dense": [_doc_id_to_key(d, by_id) for d in sr._dense_candidates(query, where, fetch_k)],  # noqa: SLF001
            "bm25": [_doc_id_to_key(d, by_id) for d in sr._bm25_candidates(query, allowed_ids, fetch_k)],  # noqa: SLF001
            "hybrid": [f'{r["lab_no"]}:{r["page"]}' for r in sr.search_slides(query, error_type="", n_results=fetch_k)],
            "hybrid_boost": [f'{r["lab_no"]}:{r["page"]}' for r in sr.search_slides(query, error_type=sample.error_type, n_results=fetch_k)],
        }

        gold_labs = {g.split(":")[0] for g in gold}
        for arm, ranked in rankings.items():
            ranked_labs = [d.split(":")[0] for d in ranked[:5]]
            results.append(ArmResult(
                sample_id=sample.sample_id,
                arm=arm,
                error_type=sample.error_type,
                lab_no=lab_no,
                recall={k: recall_at_k(ranked, gold, k) for k in k_values},
                mrr=mrr(ranked, gold),
                ndcg={k: ndcg_at_k(ranked, gold, k) for k in k_values},
                lab_recall_at5=1.0 if (set(ranked_labs) & gold_labs) else 0.0,
            ))

    if skipped_no_gold:
        print(f"Note: {skipped_no_gold} samples have no gold_slides label and were skipped "
              f"(no query-category lab covers that topic -- see slide_rag_eval.csv comments).")

    return results


def format_report(results: list[ArmResult], k_values: tuple[int, ...]) -> str:
    lines = ["# Slide RAG — Intrinsic Retrieval Evaluation", ""]
    n_samples = len({r.sample_id for r in results})
    lines.append(f"**{n_samples} gold-labeled samples**, 4 retrieval arms, k = {list(k_values)}.")
    lines.append("")
    lines.append("## Aggregate (mean, 95% bootstrap CI)")
    lines.append("")
    header = ("| Arm | " + " | ".join(f"Recall@{k}" for k in k_values) + " | MRR | "
               + " | ".join(f"nDCG@{k}" for k in k_values) + " | LabRecall@5 |")
    lines.append(header)
    lines.append("|" + "---|" * (2 + 2 * len(k_values) + 1))

    for arm in ARMS:
        arm_rows = [r for r in results if r.arm == arm]
        cells = [arm]
        for k in k_values:
            mean, lo, hi = bootstrap_ci([r.recall[k] for r in arm_rows])
            cells.append(f"{mean:.3f} [{lo:.3f}, {hi:.3f}]")
        mean, lo, hi = bootstrap_ci([r.mrr for r in arm_rows])
        cells.append(f"{mean:.3f} [{lo:.3f}, {hi:.3f}]")
        for k in k_values:
            mean, lo, hi = bootstrap_ci([r.ndcg[k] for r in arm_rows])
            cells.append(f"{mean:.3f} [{lo:.3f}, {hi:.3f}]")
        mean, lo, hi = bootstrap_ci([r.lab_recall_at5 for r in arm_rows])
        cells.append(f"{mean:.3f} [{lo:.3f}, {hi:.3f}]")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("_LabRecall@5 = did the top 5 hits include the right **deck**, even on the wrong "
                  "slide — a coarser, more forgiving signal than exact-page Recall@5._")

    lines.append("")
    lines.append("## Per-lab breakdown (Recall@5, hybrid_boost arm)")
    lines.append("")
    lines.append("| Lab | n | Recall@5 |")
    lines.append("|---|---|---|")
    hb = [r for r in results if r.arm == "hybrid_boost"]
    for lab in sorted({r.lab_no for r in hb}):
        rows = [r for r in hb if r.lab_no == lab]
        mean, _, _ = bootstrap_ci([r.recall[5] for r in rows])
        lines.append(f"| {lab} | {len(rows)} | {mean:.3f} |")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Intrinsic slide-RAG retrieval evaluation")
    parser.add_argument("--dataset-csv", default=DEFAULT_DATASET_CSV)
    parser.add_argument("--k", nargs="+", type=int, default=[1, 3, 5])
    args = parser.parse_args()

    samples = load_eval_dataset_from_csv(args.dataset_csv)
    results = run_retrieval_eval(samples, tuple(args.k))
    print(format_report(results, tuple(args.k)))


if __name__ == "__main__":
    main()
