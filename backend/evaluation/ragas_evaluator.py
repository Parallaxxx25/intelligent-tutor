"""
RAGAS Evaluator — Automated evaluation of the RAG tutoring pipeline.

Uses the RAGAS library to compute standard RAG metrics:
  - Faithfulness        : Is the hint grounded in retrieved knowledge?
  - Answer Relevancy    : Is the hint relevant to the student's error?
  - Context Precision   : Are the retrieved contexts useful?
  - Context Recall      : Did we retrieve all needed knowledge?

Plus custom hint-quality metrics:
  - Hint Level Compliance   : Does the hint match the expected scaffolding level?
  - Error Taxonomy Coverage : Are all 11 error types properly handled?
  - No Solution Leakage     : Does the hint avoid revealing the full answer?

Version: 2026-03-27
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUTO_INIT = object()


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class SampleResult:
    """Evaluation result for a single sample."""

    sample_id: str
    error_type: str
    hint_level: int
    # RAGAS metrics (0.0 – 1.0)
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    # Custom metrics (0.0 – 1.0)
    hint_level_compliance: float | None = None
    no_solution_leakage: float | None = None
    # Raw data for debugging
    generated_hint: str = ""
    retrieved_topics: list[str] = field(default_factory=list)
    expected_topics: list[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    """Aggregate evaluation report."""

    timestamp: str = ""
    total_samples: int = 0
    # Aggregate RAGAS scores
    avg_faithfulness: float = 0.0
    avg_answer_relevancy: float = 0.0
    avg_context_precision: float = 0.0
    avg_context_recall: float = 0.0
    # Aggregate custom scores
    avg_hint_level_compliance: float = 0.0
    avg_no_solution_leakage: float = 0.0
    # Coverage
    error_types_covered: int = 0
    error_types_total: int = 11
    taxonomy_coverage_pct: float = 0.0
    # Per-sample detail
    sample_results: list[SampleResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Custom hint-quality metrics (non-LLM, rule-based)
# ---------------------------------------------------------------------------


def score_hint_level_compliance(
    generated_hint: str,
    expected_level: int,
) -> float:
    """
    Score whether the generated hint matches the expected scaffolding level.

    Heuristics:
      Level 1 (Attention) : Should NOT contain code examples or solutions
      Level 2 (Category)  : Should explain the error TYPE, may mention concepts
      Level 3 (Concept)   : Should contain a code example (```)
      Level 4 (Solution)  : Should contain blanks (___) or a template

    Returns a score 0.0 – 1.0.
    """
    if expected_level == 0:
        # no_error — should be congratulatory
        positive_words = ["great", "correct", "well done", "good job", "🎉"]
        matches = sum(1 for w in positive_words if w.lower() in generated_hint.lower())
        return min(1.0, matches / 2.0)

    hint_lower = generated_hint.lower()
    has_code_block = "```" in generated_hint
    has_blanks = "___" in generated_hint
    has_question = "?" in generated_hint

    if expected_level == 1:
        # Should be a nudge without code
        score = 1.0
        if has_code_block:
            score -= 0.4  # Penalty for showing code at level 1
        if has_blanks:
            score -= 0.3  # Penalty for template at level 1
        if has_question:
            score += 0.0  # Questions are fine at level 1
        return max(0.0, score)

    elif expected_level == 2:
        # Should explain the concept, maybe mention error type
        score = 0.5
        error_keywords = [
            "error",
            "issue",
            "problem",
            "mistake",
            "incorrect",
            "wrong",
            "missing",
            "type",
            "category",
        ]
        keyword_hits = sum(1 for k in error_keywords if k in hint_lower)
        score += min(0.5, keyword_hits * 0.1)
        return min(1.0, score)

    elif expected_level == 3:
        # Should contain a code example
        score = 0.3
        if has_code_block:
            score += 0.5
        if "example" in hint_lower or "similar" in hint_lower:
            score += 0.2
        return min(1.0, score)

    elif expected_level == 4:
        # Should contain blanks or a template
        score = 0.3
        if has_blanks:
            score += 0.5
        if has_code_block:
            score += 0.2
        if "fill" in hint_lower or "template" in hint_lower or "complete" in hint_lower:
            score += 0.1
        return min(1.0, score)

    return 0.5  # Default for unknown level


def score_no_solution_leakage(
    generated_hint: str,
    reference_answer: str,
) -> float:
    """
    Score whether the hint avoids leaking the full solution.

    Compares the generated hint to the reference answer. A good hint
    should NOT contain the exact SQL fix.

    Returns 1.0 if no leakage, 0.0 if full solution leaked.
    """
    if not reference_answer:
        return 1.0

    hint_lower = generated_hint.lower().strip()
    ref_lower = reference_answer.lower().strip()

    # Check for exact match (worst case)
    if ref_lower in hint_lower:
        return 0.0

    # Extract SQL-like snippets from both
    hint_sql = set(
        re.findall(
            r"\b(?:SELECT|FROM|WHERE|JOIN|ON|GROUP BY|HAVING|ORDER BY)\b[^;]*",
            hint_lower,
            re.IGNORECASE,
        )
    )
    ref_sql = set(
        re.findall(
            r"\b(?:SELECT|FROM|WHERE|JOIN|ON|GROUP BY|HAVING|ORDER BY)\b[^;]*",
            ref_lower,
            re.IGNORECASE,
        )
    )

    if not ref_sql:
        return 1.0

    # Calculate SQL overlap
    overlap = len(hint_sql & ref_sql)
    if overlap == 0:
        return 1.0

    leakage_ratio = overlap / len(ref_sql)
    return max(0.0, 1.0 - leakage_ratio)


# ---------------------------------------------------------------------------
# RAGAS evaluator class
# ---------------------------------------------------------------------------


class RagasEvaluator:
    """
    Evaluate the RAG tutoring pipeline using RAGAS metrics.

    Uses Gemini LLM via langchain_google_genai (same as the rest of the
    project) for LLM-based RAGAS metrics.
    """

    def __init__(self, llm: Any = _AUTO_INIT, embeddings: Any = _AUTO_INIT) -> None:
        explicit_llm = llm is not _AUTO_INIT
        explicit_embeddings = embeddings is not _AUTO_INIT

        self.llm = None if llm is _AUTO_INIT else llm
        self.embeddings = None if embeddings is _AUTO_INIT else embeddings

        # Auto-configure Gemini wrappers only when args are omitted.
        # Passing llm=None explicitly is treated as "disable LLM metrics".
        if not explicit_llm and not explicit_embeddings:
            self._init_ragas_llm()

    def _init_ragas_llm(self) -> None:
        """Initialise the LLM wrapper for RAGAS if not provided."""
        if self.llm is not None:
            return

        try:
            from ragas.llms import LangchainLLMWrapper
            from backend.llm import get_gemini_model

            gemini_model = get_gemini_model(temperature=0.1)
            self.llm = LangchainLLMWrapper(gemini_model)
            logger.info("RAGAS evaluator using Gemini LLM")
        except Exception as e:
            logger.warning("Could not initialise RAGAS LLM: %s", e)
            self.llm = None

        if self.embeddings is None:
            try:
                from ragas.embeddings import LangchainEmbeddingsWrapper
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                from backend.config import get_settings

                settings = get_settings()
                embeddings = GoogleGenerativeAIEmbeddings(
                    model="models/gemini-embedding-001",
                    google_api_key=settings.GOOGLE_API_KEY,
                )
                self.embeddings = LangchainEmbeddingsWrapper(embeddings)
                logger.info("RAGAS evaluator using Gemini embeddings")
            except Exception as e:
                logger.warning("Could not initialise RAGAS embeddings: %s", e)

    def evaluate_sample(
        self,
        user_input: str,
        response: str,
        retrieved_contexts: list[str],
        reference: str = "",
        expected_level: int = 1,
    ) -> dict[str, float | None]:
        """
        Evaluate a single sample using RAGAS metrics.

        Args:
            user_input: The student's question/error context.
            response: The generated hint text.
            retrieved_contexts: List of retrieved RAG document texts.
            reference: Ground truth reference answer.
            expected_level: Expected hint scaffolding level (1–4).

        Returns:
            Dict of metric_name → score (0.0–1.0).
        """
        scores: dict[str, float | None] = {}

        # Custom metrics (always computed, no LLM needed)
        scores["hint_level_compliance"] = score_hint_level_compliance(
            response, expected_level
        )
        scores["no_solution_leakage"] = score_no_solution_leakage(response, reference)

        # RAGAS metrics (need LLM)
        if self.llm is None:
            logger.warning("No LLM available — skipping RAGAS LLM-based metrics.")
            scores["faithfulness"] = None
            scores["answer_relevancy"] = None
            scores["context_precision"] = None
            scores["context_recall"] = None
            return scores

        try:
            from ragas import evaluate
            from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
            from ragas.metrics import (
                Faithfulness,
                ResponseRelevancy,
                LLMContextPrecisionWithoutReference,
                LLMContextRecall,
            )

            sample = SingleTurnSample(
                user_input=user_input,
                response=response,
                retrieved_contexts=retrieved_contexts,
                reference=reference if reference else response,
            )

            metrics = [
                Faithfulness(llm=self.llm),
                ResponseRelevancy(llm=self.llm, embeddings=self.embeddings),
                LLMContextPrecisionWithoutReference(llm=self.llm),
                LLMContextRecall(llm=self.llm),
            ]

            eval_dataset = EvaluationDataset(samples=[sample])

            result = evaluate(
                dataset=eval_dataset,
                metrics=metrics,
            )

            # Extract scores from the RAGAS result
            result_df = result.to_pandas()
            if len(result_df) > 0:
                row = result_df.iloc[0]
                scores["faithfulness"] = _safe_score(row.get("faithfulness"))
                scores["answer_relevancy"] = _safe_score(row.get("answer_relevancy"))
                scores["context_precision"] = _safe_score(
                    row.get("llm_context_precision_without_reference")
                )
                scores["context_recall"] = _safe_score(row.get("context_recall"))

        except ImportError as e:
            logger.warning("RAGAS library not installed: %s", e)
            scores["faithfulness"] = None
            scores["answer_relevancy"] = None
            scores["context_precision"] = None
            scores["context_recall"] = None
        except Exception as e:
            logger.error("RAGAS evaluation failed: %s", e)
            scores["faithfulness"] = None
            scores["answer_relevancy"] = None
            scores["context_precision"] = None
            scores["context_recall"] = None

        return scores

    def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> EvaluationReport:
        """
        Evaluate a batch of samples and produce an aggregate report.

        Args:
            samples: List of dicts with keys:
                user_input, response, retrieved_contexts, reference,
                sample_id, error_type, hint_level, expected_topics.

        Returns:
            An EvaluationReport with per-sample and aggregate scores.
        """
        report = EvaluationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_samples=len(samples),
        )

        error_types_seen: set[str] = set()

        for sample_data in samples:
            scores = self.evaluate_sample(
                user_input=sample_data["user_input"],
                response=sample_data["response"],
                retrieved_contexts=sample_data.get("retrieved_contexts", []),
                reference=sample_data.get("reference", ""),
                expected_level=sample_data.get("hint_level", 1),
            )

            result = SampleResult(
                sample_id=sample_data.get("sample_id", "unknown"),
                error_type=sample_data.get("error_type", "unknown"),
                hint_level=sample_data.get("hint_level", 1),
                faithfulness=scores.get("faithfulness"),
                answer_relevancy=scores.get("answer_relevancy"),
                context_precision=scores.get("context_precision"),
                context_recall=scores.get("context_recall"),
                hint_level_compliance=scores.get("hint_level_compliance"),
                no_solution_leakage=scores.get("no_solution_leakage"),
                generated_hint=sample_data.get("response", ""),
                retrieved_topics=sample_data.get("retrieved_topics", []),
                expected_topics=sample_data.get("expected_topics", []),
            )
            report.sample_results.append(result)
            error_types_seen.add(result.error_type)

        # Compute aggregates
        report.error_types_covered = len(error_types_seen)
        report.taxonomy_coverage_pct = (
            report.error_types_covered / report.error_types_total * 100
        )
        report.avg_faithfulness = _avg([r.faithfulness for r in report.sample_results])
        report.avg_answer_relevancy = _avg(
            [r.answer_relevancy for r in report.sample_results]
        )
        report.avg_context_precision = _avg(
            [r.context_precision for r in report.sample_results]
        )
        report.avg_context_recall = _avg(
            [r.context_recall for r in report.sample_results]
        )
        report.avg_hint_level_compliance = _avg(
            [r.hint_level_compliance for r in report.sample_results]
        )
        report.avg_no_solution_leakage = _avg(
            [r.no_solution_leakage for r in report.sample_results]
        )

        return report


# ---------------------------------------------------------------------------
# Report formatters
# ---------------------------------------------------------------------------


def format_report_markdown(report: EvaluationReport) -> str:
    """Format the evaluation report as Markdown."""
    lines = [
        "# RAGAS Evaluation Report",
        "",
        f"**Date:** {report.timestamp}",
        f"**Samples:** {report.total_samples}",
        "",
        "## Aggregate Scores",
        "",
        "| Metric | Score |",
        "|--------|-------|",
        f"| Faithfulness | {_fmt(report.avg_faithfulness)} |",
        f"| Answer Relevancy | {_fmt(report.avg_answer_relevancy)} |",
        f"| Context Precision | {_fmt(report.avg_context_precision)} |",
        f"| Context Recall | {_fmt(report.avg_context_recall)} |",
        f"| Hint Level Compliance | {_fmt(report.avg_hint_level_compliance)} |",
        f"| No Solution Leakage | {_fmt(report.avg_no_solution_leakage)} |",
        "",
        "## Error Taxonomy Coverage",
        "",
        f"**{report.error_types_covered} / {report.error_types_total}** "
        f"error types covered ({report.taxonomy_coverage_pct:.0f}%)",
        "",
        "## Per-Sample Results",
        "",
        "| Sample | Error Type | Level | Faithfulness | Relevancy | Ctx Precision | Ctx Recall | Level Compliance | No Leakage |",
        "|--------|-----------|-------|-------------|-----------|---------------|------------|-----------------|-----------|",
    ]

    for r in report.sample_results:
        lines.append(
            f"| {r.sample_id} | {r.error_type} | {r.hint_level} "
            f"| {_fmt(r.faithfulness)} | {_fmt(r.answer_relevancy)} "
            f"| {_fmt(r.context_precision)} | {_fmt(r.context_recall)} "
            f"| {_fmt(r.hint_level_compliance)} | {_fmt(r.no_solution_leakage)} |"
        )

    return "\n".join(lines)


def format_report_json(report: EvaluationReport) -> str:
    """Format the evaluation report as JSON."""
    data = {
        "timestamp": report.timestamp,
        "total_samples": report.total_samples,
        "aggregate_scores": {
            "faithfulness": report.avg_faithfulness,
            "answer_relevancy": report.avg_answer_relevancy,
            "context_precision": report.avg_context_precision,
            "context_recall": report.avg_context_recall,
            "hint_level_compliance": report.avg_hint_level_compliance,
            "no_solution_leakage": report.avg_no_solution_leakage,
        },
        "taxonomy_coverage": {
            "covered": report.error_types_covered,
            "total": report.error_types_total,
            "percent": report.taxonomy_coverage_pct,
        },
        "sample_results": [
            {
                "sample_id": r.sample_id,
                "error_type": r.error_type,
                "hint_level": r.hint_level,
                "faithfulness": r.faithfulness,
                "answer_relevancy": r.answer_relevancy,
                "context_precision": r.context_precision,
                "context_recall": r.context_recall,
                "hint_level_compliance": r.hint_level_compliance,
                "no_solution_leakage": r.no_solution_leakage,
            }
            for r in report.sample_results
        ],
    }
    return json.dumps(data, indent=2, default=str)


def format_report_csv(report: EvaluationReport) -> str:
    """Format the evaluation report as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "sample_id",
            "error_type",
            "hint_level",
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
            "hint_level_compliance",
            "no_solution_leakage",
        ]
    )

    # Per-sample rows
    for r in report.sample_results:
        writer.writerow(
            [
                r.sample_id,
                r.error_type,
                r.hint_level,
                _fmt_csv(r.faithfulness),
                _fmt_csv(r.answer_relevancy),
                _fmt_csv(r.context_precision),
                _fmt_csv(r.context_recall),
                _fmt_csv(r.hint_level_compliance),
                _fmt_csv(r.no_solution_leakage),
            ]
        )

    # Blank row + aggregates
    writer.writerow([])
    writer.writerow(
        [
            "AVERAGE",
            "",
            "",
            _fmt_csv(report.avg_faithfulness),
            _fmt_csv(report.avg_answer_relevancy),
            _fmt_csv(report.avg_context_precision),
            _fmt_csv(report.avg_context_recall),
            _fmt_csv(report.avg_hint_level_compliance),
            _fmt_csv(report.avg_no_solution_leakage),
        ]
    )

    # Coverage row
    writer.writerow([])
    writer.writerow(
        [
            "TAXONOMY_COVERAGE",
            f"{report.error_types_covered}/{report.error_types_total}",
            f"{report.taxonomy_coverage_pct:.0f}%",
        ]
    )

    return output.getvalue()


def export_report_csv(report: EvaluationReport, filepath: str | Path) -> Path:
    """Write the evaluation report to a CSV file."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_content = format_report_csv(report)
    path.write_text(csv_content, encoding="utf-8")
    logger.info("Evaluation results exported to %s", path)
    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _avg(values: list[float | None]) -> float:
    """Average of non-None values, 0.0 if all None."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else 0.0


def _safe_score(value: Any) -> float | None:
    """Safely convert a RAGAS score to float."""
    if value is None:
        return None
    try:
        score = float(value)
        if 0.0 <= score <= 1.0:
            return score
        return max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None) -> str:
    """Format a score for markdown display."""
    return f"{value:.3f}" if value is not None else "N/A"


def _fmt_csv(value: float | None) -> str:
    """Format a score for CSV display."""
    return f"{value:.4f}" if value is not None else ""
