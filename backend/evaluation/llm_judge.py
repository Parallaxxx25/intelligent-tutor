"""
OpenRouter LLM-as-a-Judge API Client.

Uses OpenRouter API explicitly with model `openai/gpt-oss-120b` (or similar)
to evaluate the generated SQL hints against standard references and context.

Version: 2026-03-28
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict
from dataclasses import dataclass, field
import csv
import io

from backend.config import get_settings
from backend.evaluation.ragas_evaluator import (
    _avg,
    score_hint_level_compliance,
    score_no_solution_leakage,
)

logger = logging.getLogger(__name__)


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "N/A"


def _fmt_csv(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else ""


@dataclass
class JudgeSampleResult:
    sample_id: str
    error_type: str
    hint_level: int
    hint_level_compliance: float | None = None
    no_solution_leakage: float | None = None
    judge_quality_score: float | None = None
    judge_rationale: str = ""
    generated_hint: str = ""
    retrieved_topics: list[str] = field(default_factory=list)
    expected_topics: list[str] = field(default_factory=list)


@dataclass
class JudgeEvaluationReport:
    timestamp: str = ""
    total_samples: int = 0
    avg_hint_level_compliance: float = 0.0
    avg_no_solution_leakage: float = 0.0
    avg_judge_quality_score: float = 0.0
    error_types_covered: int = 0
    error_types_total: int = 11
    taxonomy_coverage_pct: float = 0.0
    sample_results: list[JudgeSampleResult] = field(default_factory=list)


def format_judge_report_markdown(report: JudgeEvaluationReport) -> str:
    lines = [
        "# OpenRouter LLM Judge Evaluation Report",
        "",
        f"**Date:** {report.timestamp}",
        f"**Samples:** {report.total_samples}",
        "",
        "## Aggregate Scores",
        "",
        "| Metric | Score |",
        "|--------|-------|",
        f"| Hint Level Compliance | {_fmt(report.avg_hint_level_compliance)} |",
        f"| No Solution Leakage | {_fmt(report.avg_no_solution_leakage)} |",
        f"| LLM Judge Quality Score | {_fmt(report.avg_judge_quality_score)} |",
        "",
        "## Error Taxonomy Coverage",
        "",
        f"**{report.error_types_covered} / {report.error_types_total}** "
        f"error types covered ({report.taxonomy_coverage_pct:.0f}%)",
        "",
        "## Per-Sample Results",
        "",
        "| Sample | Error Type | Level | Level Compliance | No Leakage | Judge Score | Judge Rationale |",
        "|--------|-----------|-------|-----------------|-----------|-------------|-----------------|",
    ]

    for r in report.sample_results:
        rationale_excerpt = (
            r.judge_rationale[:40] + "..."
            if r.judge_rationale and len(r.judge_rationale) > 40
            else (r.judge_rationale or "N/A")
        )
        lines.append(
            f"| {r.sample_id} | {r.error_type} | {r.hint_level} "
            f"| {_fmt(r.hint_level_compliance)} | {_fmt(r.no_solution_leakage)} "
            f"| {_fmt(r.judge_quality_score)} | {rationale_excerpt} |"
        )
    return "\n".join(lines)


def format_judge_report_json(report: JudgeEvaluationReport) -> str:
    data = {
        "timestamp": report.timestamp,
        "total_samples": report.total_samples,
        "aggregate_scores": {
            "hint_level_compliance": report.avg_hint_level_compliance,
            "no_solution_leakage": report.avg_no_solution_leakage,
            "judge_quality_score": report.avg_judge_quality_score,
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
                "hint_level_compliance": r.hint_level_compliance,
                "no_solution_leakage": r.no_solution_leakage,
                "judge_quality_score": r.judge_quality_score,
                "judge_rationale": r.judge_rationale,
            }
            for r in report.sample_results
        ],
    }
    return json.dumps(data, indent=2, default=str)


def format_judge_report_csv(report: JudgeEvaluationReport) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "sample_id",
            "error_type",
            "hint_level",
            "hint_level_compliance",
            "no_solution_leakage",
            "judge_quality_score",
            "judge_rationale",
        ]
    )
    for r in report.sample_results:
        writer.writerow(
            [
                r.sample_id,
                r.error_type,
                r.hint_level,
                _fmt_csv(r.hint_level_compliance),
                _fmt_csv(r.no_solution_leakage),
                _fmt_csv(r.judge_quality_score),
                r.judge_rationale,
            ]
        )
    writer.writerow([])
    writer.writerow(
        [
            "AVERAGE",
            "",
            "",
            _fmt_csv(report.avg_hint_level_compliance),
            _fmt_csv(report.avg_no_solution_leakage),
            _fmt_csv(report.avg_judge_quality_score),
            "",
        ]
    )
    writer.writerow([])
    writer.writerow(
        [
            "TAXONOMY_COVERAGE",
            f"{report.error_types_covered}/{report.error_types_total}",
            f"{report.taxonomy_coverage_pct:.0f}%",
        ]
    )
    return output.getvalue()


def export_judge_report_csv(
    report: JudgeEvaluationReport, filepath: str | os.PathLike
) -> Path:
    from pathlib import Path

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_content = format_judge_report_csv(report)
    path.write_text(csv_content, encoding="utf-8")
    logger.info("OpenRouter judge results exported to %s", path)
    return path


class OpenRouterJudge:
    """Evaluates SQL tutoring hints using an OpenRouter LLM as a judge."""

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        settings = get_settings()
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = model
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        if not self.api_key:
            logger.warning(
                "OPENROUTER_API_KEY is not set. The OpenRouterJudge will not function properly."
            )

    def evaluate_sample(
        self,
        generated_hint: str,
        reference_answer: str,
        error_type: str,
        hint_level: int,
    ) -> dict[str, Any]:
        """
        Calls OpenRouter API to evaluate a hint.

        Returns a dictionary with 'judge_quality_score' (0.0 to 1.0) and 'judge_rationale'.
        """
        if not self.api_key:
            return {"judge_quality_score": None, "judge_rationale": "Missing API key."}

        system_prompt = (
            "You are an expert SQL teacher and evaluator. "
            "Your task is to evaluate the quality of a hint generated by a tutoring system. "
            "You will be given the generated hint, the reference (ground truth) hint, "
            "the error type the student made, and the target hint level (1=Attention, 2=Category, 3=Example, 4=Template). "
            "Evaluate pedagogical quality, correctness, and adherence to the hint level.\n"
            "Return a JSON object with strictly these two keys:\n"
            '  "score": a float between 0.0 and 1.0 (where 1.0 is highest quality)\n'
            '  "rationale": a short string explaining the score'
        )

        user_prompt = (
            f"Error Type: {error_type}\n"
            f"Target Hint Level: {hint_level}\n\n"
            f"Reference Hint:\n{reference_answer}\n\n"
            f"Generated Hint to Evaluate:\n{generated_hint}\n"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/Parallaxxx25/intelligent-tutor",  # Example referer
            "Content-Type": "application/json",
        }

        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        try:
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(data).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req) as response:
                body = response.read()
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                score = float(parsed.get("score", 0.0))
                rationale = str(parsed.get("rationale", "No rationale provided."))

                # Ensure score is bound 0.0 - 1.0
                score = max(0.0, min(1.0, score))

                return {"judge_quality_score": score, "judge_rationale": rationale}

        except Exception as e:
            logger.error("OpenRouter API call failed: %s", e)
            return {"judge_quality_score": None, "judge_rationale": f"API error: {e}"}

    def evaluate_batch(
        self, eval_samples: list[dict[str, Any]]
    ) -> JudgeEvaluationReport:
        """
        Evaluates a batch of samples strictly using the OpenRouter LLM judge.
        Returns a JudgeEvaluationReport with ONLY judge scores (and rule-based).
        """
        from datetime import datetime, timezone
        from backend.evaluation.ragas_evaluator import (
            score_hint_level_compliance,
            score_no_solution_leakage,
        )

        logger.info("Starting purely OpenRouter LLM-as-a-judge evaluation...")

        report = JudgeEvaluationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_samples=len(eval_samples),
        )

        error_types_seen = set()

        for sample_data in eval_samples:
            generated_hint = sample_data.get("response", "")
            reference = sample_data.get("reference", "")
            error_type = sample_data.get("error_type", "unknown")
            hint_level = sample_data.get("hint_level", 1)

            judge_res = self.evaluate_sample(
                generated_hint=generated_hint,
                reference_answer=reference,
                error_type=error_type,
                hint_level=hint_level,
            )

            # Compute rule-based custom metrics alongside judge
            level_compliance = score_hint_level_compliance(generated_hint, hint_level)
            no_leakage = score_no_solution_leakage(generated_hint, reference)

            result = JudgeSampleResult(
                sample_id=sample_data.get("sample_id", "unknown"),
                error_type=error_type,
                hint_level=hint_level,
                generated_hint=generated_hint,
                retrieved_topics=sample_data.get("retrieved_topics", []),
                expected_topics=sample_data.get("expected_topics", []),
                hint_level_compliance=level_compliance,
                no_solution_leakage=no_leakage,
                judge_quality_score=judge_res.get("judge_quality_score"),
                judge_rationale=judge_res.get("judge_rationale", ""),
            )
            report.sample_results.append(result)
            error_types_seen.add(result.error_type)

        # Compute aggregates
        report.error_types_covered = len(error_types_seen)
        report.taxonomy_coverage_pct = (
            report.error_types_covered / report.error_types_total * 100
        )
        report.avg_hint_level_compliance = _avg(
            [r.hint_level_compliance for r in report.sample_results]
        )
        report.avg_no_solution_leakage = _avg(
            [r.no_solution_leakage for r in report.sample_results]
        )
        report.avg_judge_quality_score = _avg(
            [r.judge_quality_score for r in report.sample_results]
        )

        return report

    # Note: evaluate_and_augment is no longer strictly needed in standalone mode, but kept for compatibility.
    def evaluate_and_augment(
        self, report: Any, eval_samples: list[dict[str, Any]]
    ) -> Any:
        """
        Extends the `EvaluationReport` by evaluating each sample with OpenRouter.
        """
        logger.info("Starting OpenRouter LLM-as-a-judge evaluation...")

        # Map samples by sample_id for quick lookup
        sample_dict = {s["sample_id"]: s for s in eval_samples}

        for result in report.sample_results:
            raw_sample = sample_dict.get(result.sample_id, {})
            # reference might not be in sample dict if not passed correctly, fallback
            reference = raw_sample.get("reference", "")

            judge_res = self.evaluate_sample(
                generated_hint=result.generated_hint,
                reference_answer=reference,
                error_type=result.error_type,
                hint_level=result.hint_level,
            )
            result.judge_quality_score = judge_res.get("judge_quality_score")
            result.judge_rationale = judge_res.get("judge_rationale", "")

        # Compute average
        report.avg_judge_quality_score = _avg(
            [r.judge_quality_score for r in report.sample_results]
        )

        return report


def _avg(values: list[float | None]) -> float:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else 0.0
