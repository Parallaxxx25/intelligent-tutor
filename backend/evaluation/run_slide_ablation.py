"""
Extrinsic hint-quality ablation for the slide-material RAG layer.

Answers: does slide context actually make hints better, and is it safe (no
Oracle-HR-schema leakage)? Three arms, run through the real production path
(`supervisor.diagnose_and_hint`), never a reimplementation of it:

    no_rag          -- curated KB off, slide RAG off
    curated         -- curated KB on,  slide RAG off  (today's non-slide baseline)
    curated_slides  -- curated KB on,  slide RAG on   (what run_pipeline_llm actually does)

Companion to slide_retrieval_eval.py (intrinsic retrieval quality, free, no
LLM). Run that first — if hybrid retrieval doesn't beat single-mode there,
these numbers won't mean anything either.

Usage:
    python -m backend.evaluation.run_slide_ablation --repeats 1 --limit 3   # smoke test
    python -m backend.evaluation.run_slide_ablation --repeats 3 --output csv \\
        --csv-path slide_ablation.csv --emit-human-sheet
    python -m backend.evaluation.run_slide_ablation --score-human human_rating_sheet.csv

Version: 2026-08-29
"""

from __future__ import annotations

import sys

# Windows consoles default to cp1252, which chokes on "—" and Thai text
# in the report strings this module prints.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import csv
import io
import logging
import os
import random
import re
from dataclasses import dataclass
from typing import Any, Callable

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DATASET_CSV = "backend/evaluation/data/slide_rag_eval.csv"
ARMS = ("no_rag", "curated", "curated_slides")


# ---------------------------------------------------------------------------
# Stats helpers (stdlib only -- see slide_retrieval_eval.py for the sibling
# copy; six short functions used by one caller each, not worth a shared module)
# ---------------------------------------------------------------------------

def bootstrap_ci(values: list[float], n_resamples: int = 10_000, seed: int = 0) -> tuple[float, float, float]:
    """(mean, lo95, hi95) via percentile bootstrap over paired deltas."""
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


def spearman_rho(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation, stdlib only. Ties broken by average rank."""
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    if len(xs) < 2:
        return 0.0
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - (6 * d2) / (n * (n**2 - 1))


# ---------------------------------------------------------------------------
# Arm switching -- no production code changes needed. diagnose_and_hint
# imports retrieve_relevant_context *inside* the function body and reads
# SLIDE_RAG_ENABLED from get_settings() at call time (both lru_cache'd), so
# an env var + a monkeypatch fully control what each arm sees.
# ---------------------------------------------------------------------------

class ArmContext:
    """Context manager: switches curated-KB + slide-RAG behavior for one arm."""

    def __init__(self, arm: str):
        self.arm = arm
        self._orig_retrieve: Callable | None = None
        self._orig_env: str | None = None

    def __enter__(self):
        import backend.rag.retriever as retriever_mod
        from backend.config import get_settings

        self._orig_retrieve = retriever_mod.retrieve_relevant_context
        self._orig_env = os.environ.get("SLIDE_RAG_ENABLED")

        if self.arm == "no_rag":
            retriever_mod.retrieve_relevant_context = lambda **kw: []
            os.environ["SLIDE_RAG_ENABLED"] = "false"
        elif self.arm == "curated":
            os.environ["SLIDE_RAG_ENABLED"] = "false"
        elif self.arm == "curated_slides":
            os.environ["SLIDE_RAG_ENABLED"] = "true"
        else:
            raise ValueError(f"unknown arm: {self.arm}")

        get_settings.cache_clear()
        return self

    def __exit__(self, *exc):
        import backend.rag.retriever as retriever_mod
        from backend.config import get_settings

        retriever_mod.retrieve_relevant_context = self._orig_retrieve
        if self._orig_env is None:
            os.environ.pop("SLIDE_RAG_ENABLED", None)
        else:
            os.environ["SLIDE_RAG_ENABLED"] = self._orig_env
        get_settings.cache_clear()
        return False


def _init_kbs() -> None:
    """diagnose_and_hint expects both KBs already initialized -- nothing
    does that for a standalone script the way main.py's lifespan does."""
    from backend.rag.retriever import initialize_knowledge_base
    from backend.rag.slide_retriever import initialize_slide_kb

    try:
        initialize_knowledge_base(persist_dir=None)
    except Exception as e:
        logger.warning("Curated KB init failed (non-fatal, matches prod degrade): %s", e)
    try:
        initialize_slide_kb()
    except Exception as e:
        logger.warning("Slide KB init failed (non-fatal, matches prod degrade): %s", e)


# ---------------------------------------------------------------------------
# Running one (sample, arm, repeat)
# ---------------------------------------------------------------------------

@dataclass
class HintRun:
    sample_id: str
    arm: str
    repeat: int
    error_type: str
    hint_level: int
    hint_text: str
    hint_source: str
    guardrail_fallback: bool
    hr_leak_detected: bool
    citation_present: bool
    citation_correct: bool | None  # None when arm != curated_slides or no gold lab
    judge_quality_score: float | None
    judge_rationale: str
    hint_level_compliance: float | None
    no_solution_leakage: float | None


def _grading_raw(sample) -> dict[str, Any]:
    return {
        "test_results": [{"passed": False, "detail": sample.error_message}],
        "student_error": sample.error_message,
        "student_error_type": sample.error_type,
    }


def run_one(sample, arm: str, repeat: int, judge) -> HintRun:
    from backend.agents.supervisor import diagnose_and_hint
    from backend.evaluation.ragas_evaluator import (
        score_hint_level_compliance,
        score_no_solution_leakage,
    )
    from backend.guardrails import _HR_SCHEMA_LEAK_PATTERN

    with ArmContext(arm):
        diagnosis, hint = diagnose_and_hint(
            student_code=sample.student_query,
            grading_raw=_grading_raw(sample),
            problem_description=sample.problem_description,
            problem_topic=sample.error_type,
            attempt_count=sample.attempt_count,
        )

    guardrail_fallback = hint.source == "rule_based" and hint.fallback_reason == "guardrail"
    hr_leak = bool(_HR_SCHEMA_LEAK_PATTERN.search(hint.hint_text))

    # \bLAB\s*\d+\b, not a bare "LAB" substring -- "available"/"table"/
    # "collaborate" all contain "lab" and would otherwise false-positive.
    mentioned_labs = set(re.findall(r"\bLAB\s*(\d+)\b", hint.hint_text, re.IGNORECASE))
    citation_present = bool(mentioned_labs)
    citation_correct = None
    if arm == "curated_slides" and sample.gold_slides:
        gold_labs = {g.split(":")[0] for g in sample.gold_slides}
        citation_correct = bool(mentioned_labs & gold_labs) if citation_present else False

    judge_score, judge_rationale = None, ""
    if judge is not None:
        res = judge.evaluate_sample(
            generated_hint=hint.hint_text,
            reference_answer=sample.reference_answer,
            error_type=sample.error_type,
            hint_level=hint.hint_level,
        )
        judge_score = res.get("judge_quality_score")
        judge_rationale = res.get("judge_rationale", "")

    return HintRun(
        sample_id=sample.sample_id,
        arm=arm,
        repeat=repeat,
        error_type=sample.error_type,
        hint_level=hint.hint_level,
        hint_text=hint.hint_text,
        hint_source=hint.source,
        guardrail_fallback=guardrail_fallback,
        hr_leak_detected=hr_leak,
        citation_present=citation_present,
        citation_correct=citation_correct,
        judge_quality_score=judge_score,
        judge_rationale=judge_rationale,
        hint_level_compliance=score_hint_level_compliance(hint.hint_text, hint.hint_level),
        no_solution_leakage=score_no_solution_leakage(hint.hint_text, sample.reference_answer),
    )


def run_ablation(samples: list, repeats: int, use_judge: bool, limit: int | None = None) -> list[HintRun]:
    from backend.evaluation.llm_judge import OpenRouterJudge

    _init_kbs()
    judge = OpenRouterJudge() if use_judge else None
    if use_judge and not judge.api_key:
        logger.warning("OPENROUTER_API_KEY not set -- judge_quality_score will be empty.")

    todo = samples[:limit] if limit else samples
    runs: list[HintRun] = []
    total = len(todo) * len(ARMS) * repeats
    done = 0

    for repeat in range(1, repeats + 1):
        for sample in todo:
            for arm in ARMS:
                runs.append(run_one(sample, arm, repeat, judge))
                done += 1
                if done % 10 == 0 or done == total:
                    logger.info("Progress: %d/%d hints generated", done, total)

    if hr_leaks := [r for r in runs if r.hr_leak_detected]:
        logger.error(
            "%d served hints contain raw HR-schema terms -- guardrail bug, not a RAG "
            "result (validate_output should have sanitized/blocked these): %s",
            len(hr_leaks), [r.sample_id for r in hr_leaks],
        )

    return runs


# ---------------------------------------------------------------------------
# Aggregation + report
# ---------------------------------------------------------------------------

def _mean_by_sample(runs: list[HintRun], arm: str, metric: Callable[[HintRun], float | None]) -> dict[str, float]:
    """Average `metric` across repeats, per sample_id, for one arm."""
    by_sample: dict[str, list[float]] = {}
    for r in runs:
        if r.arm != arm:
            continue
        v = metric(r)
        if v is not None:
            by_sample.setdefault(r.sample_id, []).append(v)
    return {sid: sum(vs) / len(vs) for sid, vs in by_sample.items()}


def paired_delta(runs: list[HintRun], arm_a: str, arm_b: str, metric: Callable[[HintRun], float | None]) -> list[float]:
    """[metric(b) - metric(a)] for every sample present in both arms."""
    a = _mean_by_sample(runs, arm_a, metric)
    b = _mean_by_sample(runs, arm_b, metric)
    common = set(a) & set(b)
    return [b[sid] - a[sid] for sid in common]


def format_report(runs: list[HintRun]) -> str:
    lines = ["# Slide RAG — Extrinsic Hint-Quality Ablation", ""]
    n_samples = len({r.sample_id for r in runs})
    repeats = len({r.repeat for r in runs})
    lines.append(f"**{n_samples} samples** × **{len(ARMS)} arms** × **{repeats} repeats** "
                 f"= {len(runs)} hints generated via `supervisor.diagnose_and_hint` "
                 f"(the real production path).")
    lines.append("")

    metrics: dict[str, Callable[[HintRun], float | None]] = {
        "judge_quality": lambda r: r.judge_quality_score,
        "level_compliance": lambda r: r.hint_level_compliance,
        "no_leakage": lambda r: r.no_solution_leakage,
        "citation_rate": lambda r: 1.0 if r.citation_present else 0.0,
        "guardrail_fallback_rate": lambda r: 1.0 if r.guardrail_fallback else 0.0,
    }

    lines.append("## Per-arm means (mean, 95% bootstrap CI over per-sample averages)")
    lines.append("")
    lines.append("| Arm | " + " | ".join(metrics) + " |")
    lines.append("|" + "---|" * (1 + len(metrics)))
    for arm in ARMS:
        cells = [arm]
        for name, fn in metrics.items():
            per_sample = list(_mean_by_sample(runs, arm, fn).values())
            mean, lo, hi = bootstrap_ci(per_sample)
            cells.append(f"{mean:.3f} [{lo:.3f}, {hi:.3f}]")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Citation correctness (curated_slides arm only, samples with a gold slide)")
    lines.append("")
    cs_runs = [r for r in runs if r.arm == "curated_slides" and r.citation_correct is not None]
    if cs_runs:
        correct_rate = sum(1 for r in cs_runs if r.citation_correct) / len(cs_runs)
        lines.append(f"Of hints that cite a LAB, {correct_rate:.1%} cite the *correct* lab "
                     f"(n={len(cs_runs)}).")
    else:
        lines.append("No samples with both a gold slide label and a citing hint.")
    lines.append("")

    lines.append("## Paired deltas (curated_slides − curated, i.e. slide RAG's marginal effect)")
    lines.append("")
    lines.append("| Metric | Mean Δ | 95% CI |")
    lines.append("|---|---|---|")
    for name, fn in metrics.items():
        if name == "guardrail_fallback_rate":
            continue  # reported separately below, direction of "good" flips
        deltas = paired_delta(runs, "curated", "curated_slides", fn)
        mean, lo, hi = bootstrap_ci(deltas)
        lines.append(f"| {name} | {mean:+.3f} | [{lo:+.3f}, {hi:+.3f}] |")
    lines.append("")

    lines.append("## Safety: guardrail fallback rate by arm (HR-schema leak caught before serving)")
    lines.append("")
    for arm in ("curated", "curated_slides"):
        rate = sum(1 for r in runs if r.arm == arm and r.guardrail_fallback) / max(
            1, sum(1 for r in runs if r.arm == arm)
        )
        lines.append(f"- `{arm}`: {rate:.1%} of hints fell back to rule-based due to a guardrail hit")
    n_raw_leaks = sum(1 for r in runs if r.hr_leak_detected)
    lines.append(f"- Raw HR-schema terms in a *served* hint: {n_raw_leaks} "
                 f"(must be 0 — non-zero is a guardrail bug, not a RAG measurement)")
    lines.append("")

    lines.append("## Per-error-type breakdown (judge_quality, curated_slides arm)")
    lines.append("")
    by_type: dict[str, list[float]] = {}
    for r in runs:
        if r.arm == "curated_slides" and r.judge_quality_score is not None:
            by_type.setdefault(r.error_type, []).append(r.judge_quality_score)
    lines.append("| Error type | n | mean judge score |")
    lines.append("|---|---|---|")
    for et in sorted(by_type):
        vs = by_type[et]
        lines.append(f"| {et} | {len(vs)} | {sum(vs)/len(vs):.3f} |")

    return "\n".join(lines)


def format_csv(runs: list[HintRun]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "sample_id", "arm", "repeat", "error_type", "hint_level", "hint_source",
        "guardrail_fallback", "hr_leak_detected", "citation_present", "citation_correct",
        "judge_quality_score", "hint_level_compliance", "no_solution_leakage",
        "judge_rationale", "hint_text",
    ])
    for r in runs:
        writer.writerow([
            r.sample_id, r.arm, r.repeat, r.error_type, r.hint_level, r.hint_source,
            int(r.guardrail_fallback), int(r.hr_leak_detected), int(r.citation_present),
            "" if r.citation_correct is None else int(r.citation_correct),
            "" if r.judge_quality_score is None else f"{r.judge_quality_score:.4f}",
            "" if r.hint_level_compliance is None else f"{r.hint_level_compliance:.4f}",
            "" if r.no_solution_leakage is None else f"{r.no_solution_leakage:.4f}",
            r.judge_rationale, r.hint_text,
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Human Likert sub-sample (Step 5)
# ---------------------------------------------------------------------------

def emit_human_sheet(runs: list[HintRun], n_per_arm: int = 15, seed: int = 0, samples_by_id: dict | None = None) -> tuple[str, str]:
    """Stratified sample of `curated` + `curated_slides` hints (repeat=1 only,
    one hint per sample per arm), shuffled with the arm hidden. Returns
    (rating_sheet_csv, rating_key_csv)."""
    rng = random.Random(seed)
    pool = {arm: [r for r in runs if r.arm == arm and r.repeat == 1] for arm in ("curated", "curated_slides")}
    for arm in pool:
        rng.shuffle(pool[arm])

    picked = pool["curated"][:n_per_arm] + pool["curated_slides"][:n_per_arm]
    rng.shuffle(picked)

    sheet = io.StringIO()
    w = csv.writer(sheet)
    w.writerow(["rating_id", "problem", "student_query", "hint", "rating"])
    key = io.StringIO()
    kw = csv.writer(key)
    kw.writerow(["rating_id", "arm", "sample_id"])

    for i, r in enumerate(picked, start=1):
        rid = f"r{i:03d}"
        problem = samples_by_id[r.sample_id].problem_description if samples_by_id else ""
        student_query = samples_by_id[r.sample_id].student_query if samples_by_id else ""
        w.writerow([rid, problem, student_query, r.hint_text, ""])
        kw.writerow([rid, r.arm, r.sample_id])

    return sheet.getvalue(), key.getvalue()


def score_human_ratings(rating_sheet_path: str, rating_key_path: str, runs: list[HintRun]) -> str:
    ratings: dict[str, float] = {}
    with open(rating_sheet_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("rating", "").strip():
                ratings[row["rating_id"]] = float(row["rating"])

    key: dict[str, tuple[str, str]] = {}
    with open(rating_key_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key[row["rating_id"]] = (row["arm"], row["sample_id"])

    by_arm: dict[str, list[float]] = {}
    judge_paired: list[tuple[float, float]] = []
    judge_by_sample_arm = {(r.sample_id, r.arm): r.judge_quality_score for r in runs if r.repeat == 1}

    for rid, likert in ratings.items():
        if rid not in key:
            continue
        arm, sample_id = key[rid]
        by_arm.setdefault(arm, []).append(likert)
        j = judge_by_sample_arm.get((sample_id, arm))
        if j is not None:
            judge_paired.append((likert, j))

    lines = ["# Human Likert Sub-Sample Results", ""]
    lines.append(f"{len(ratings)} of {len(key)} hints rated.")
    lines.append("")
    lines.append("| Arm | n | mean Likert (1-5) |")
    lines.append("|---|---|---|")
    for arm, vs in by_arm.items():
        mean, lo, hi = bootstrap_ci(vs)
        lines.append(f"| {arm} | {len(vs)} | {mean:.2f} [{lo:.2f}, {hi:.2f}] |")
    lines.append("")
    if len(judge_paired) >= 3:
        xs, ys = zip(*judge_paired)
        rho = spearman_rho(list(xs), list(ys))
        lines.append(f"**Judge-human agreement**: Spearman ρ = {rho:.3f} "
                     f"(n={len(judge_paired)} hints with both a human rating and a judge score)")
    else:
        lines.append("Not enough paired ratings to compute judge-human correlation.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Slide-RAG extrinsic hint-quality ablation")
    parser.add_argument("--dataset-csv", default=DEFAULT_DATASET_CSV)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N samples (smoke test)")
    parser.add_argument("--no-judge", action="store_true", help="Skip the OpenRouter LLM judge (rule-based metrics only)")
    parser.add_argument("--output", choices=["markdown", "csv"], default="markdown")
    parser.add_argument("--csv-path", default="slide_ablation.csv")
    parser.add_argument("--report-path", default="slide_ablation_report.md")
    parser.add_argument("--emit-human-sheet", action="store_true")
    parser.add_argument("--human-sheet-path", default="human_rating_sheet.csv")
    parser.add_argument("--human-key-path", default="human_rating_key.csv")
    parser.add_argument("--score-human", default=None, metavar="RATING_SHEET_CSV",
                         help="Skip generation; score a filled-in human rating sheet against --human-key-path")
    args = parser.parse_args()

    from backend.evaluation.eval_dataset import load_eval_dataset_from_csv

    samples = load_eval_dataset_from_csv(args.dataset_csv)

    if args.score_human:
        # Needs the same run to reconstruct judge scores for the correlation --
        # re-running is the honest option (a cached run could go stale).
        runs = run_ablation(samples, repeats=1, use_judge=not args.no_judge, limit=args.limit)
        print(score_human_ratings(args.score_human, args.human_key_path, runs))
        return

    runs = run_ablation(samples, repeats=args.repeats, use_judge=not args.no_judge, limit=args.limit)

    report_md = format_report(runs)
    with open(args.report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Report written to {args.report_path}")
    print()
    print(report_md)

    if args.output == "csv":
        csv_text = format_csv(runs)
        with open(args.csv_path, "w", newline="", encoding="utf-8") as f:
            f.write(csv_text)
        print(f"\nCSV written to {args.csv_path}")

    if args.emit_human_sheet:
        samples_by_id = {s.sample_id: s for s in samples}
        sheet, key = emit_human_sheet(runs, samples_by_id=samples_by_id)
        with open(args.human_sheet_path, "w", newline="", encoding="utf-8") as f:
            f.write(sheet)
        with open(args.human_key_path, "w", newline="", encoding="utf-8") as f:
            f.write(key)
        print(f"\nHuman rating sheet written to {args.human_sheet_path} "
              f"(fill the 'rating' column 1-5, then re-run with --score-human).")


if __name__ == "__main__":
    main()
