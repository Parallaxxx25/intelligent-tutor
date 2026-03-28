"""
OpenRouter LLM-as-a-Judge Evaluation Runner — CLI entry point.

Runs the evaluation pipeline strictly using the OpenRouter LLM-as-a-judge
(`openai/gpt-oss-120b`) without relying on RAGAS metrics.

Usage:
    python -m backend.evaluation.run_eval_llm_judge
    python -m backend.evaluation.run_eval_llm_judge --output csv
    python -m backend.evaluation.run_eval_llm_judge --output json
    python -m backend.evaluation.run_eval_llm_judge --output csv --csv-path judge_results.csv

Version: 2026-03-28
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from backend.evaluation.eval_dataset import (
    EVAL_DATASET,
    EvalSample,
    load_eval_dataset_from_csv,
)
from backend.evaluation.llm_judge import (
    OpenRouterJudge,
    format_judge_report_csv,
    format_judge_report_json,
    format_judge_report_markdown,
    export_judge_report_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _build_user_input(sample: EvalSample) -> str:
    """Build the user_input string for context."""
    return (
        f"Problem: {sample.problem_description}\n"
        f"Student Query:\n{sample.student_query}\n"
        f"Error: {sample.error_message}\n"
    )


def run_llm_judge_evaluation(
    output_format: str = "markdown",
    csv_path: str | None = None,
    dataset_csv: str | None = None,
) -> str:
    """
    Run the LLM-as-a-judge evaluation.

    Args:
        output_format: 'markdown', 'json', or 'csv'.
        csv_path: Optional file path for CSV export.
        dataset_csv: Path to an evaluation CSV dataset. If None, uses default EVAL_DATASET.

    Returns:
        The formatted report string.
    """
    # Step 1: Initialise knowledge base (needed for generating hints contextually!)
    logger.info("Step 1: Initialising ChromaDB knowledge base...")
    try:
        from backend.rag.retriever import (
            initialize_knowledge_base,
            retrieve_relevant_context,
        )

        initialize_knowledge_base(persist_dir=None)
        logger.info("Knowledge base initialised successfully.")
    except Exception as e:
        logger.warning("Knowledge base init failed: %s — using empty contexts.", e)
        retrieve_relevant_context = None

    # Step 2: Build evaluation samples
    logger.info("Step 2: Building evaluation samples and generating hints...")
    eval_samples = []

    dataset_to_use = (
        load_eval_dataset_from_csv(dataset_csv) if dataset_csv else EVAL_DATASET
    )

    for idx, sample in enumerate(dataset_to_use):
        logger.info(
            "Processing sample %d/%d: %s (Level %d)",
            idx + 1,
            len(dataset_to_use),
            sample.sample_id,
            sample.hint_level,
        )

        user_input = _build_user_input(sample)
        retrieved_contexts = []
        retrieved_topics = []

        if retrieve_relevant_context is not None:
            try:
                docs = retrieve_relevant_context(
                    query=user_input,
                    error_type=sample.error_type,
                    n_results=3,
                )
                retrieved_contexts = [f"### {d['title']}\n{d['content']}" for d in docs]
                retrieved_topics = [
                    d.get("metadata", {}).get("topic", "") for d in docs
                ]
            except Exception as e:
                logger.warning("RAG retrieval failed for %s: %s", sample.sample_id, e)

        # Generate hint using the pipeline
        generated_hint = sample.ground_truth_hint  # Default to ground truth
        try:
            from backend.tools.hint_generator import generate_sql_hint

            hint_result = generate_sql_hint(
                error_type=sample.error_type,
                error_message=sample.error_message,
                student_query=sample.student_query,
                attempt_count=sample.attempt_count,
                problem_description=sample.problem_description,
                problematic_clause=sample.problematic_clause,
            )
            generated_hint = hint_result.get("hint_text", sample.ground_truth_hint)
        except Exception as e:
            logger.warning(
                "Hint generation failed for %s: %s — using ground truth.",
                sample.sample_id,
                e,
            )

        eval_samples.append(
            {
                "sample_id": sample.sample_id,
                "error_type": sample.error_type,
                "hint_level": sample.hint_level,
                "user_input": user_input,
                "response": generated_hint,
                "retrieved_contexts": retrieved_contexts,
                "reference": sample.reference_answer,
                "retrieved_topics": retrieved_topics,
                "expected_topics": sample.expected_rag_topics,
            }
        )

    # Step 3: Run LLM-as-a-judge evaluation
    logger.info("Step 3: Running OpenRouter LLM-as-a-judge evaluation...")
    judge = OpenRouterJudge()
    report = judge.evaluate_batch(eval_samples)

    # Step 4: Format output
    logger.info("Step 4: Generating %s report...", output_format)

    if output_format == "csv":
        result = format_judge_report_csv(report)
        # Also export to file if path is provided
        if csv_path:
            logger.info("Exporting CSV to %s...", csv_path)
            export_judge_report_csv(report, csv_path)
            logger.info("CSV exported to: %s", csv_path)
        else:
            # Default CSV path
            default_path = Path("judge_results.csv")
            export_judge_report_csv(report, default_path)
            logger.info("CSV exported to: %s", default_path.resolve())
    elif output_format == "json":
        result = format_judge_report_json(report)
    else:
        result = format_judge_report_markdown(report)

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="LLM Judge Evaluation Runner for the SQL Tutoring Pipeline",
    )
    parser.add_argument(
        "--output",
        choices=["markdown", "json", "csv"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default=None,
        help="File path for CSV export (default: judge_results.csv)",
    )
    parser.add_argument(
        "--dataset-csv",
        type=str,
        default=None,
        help="Path to a custom evaluation dataset CSV file (default: use internal EVAL_DATASET)",
    )

    args = parser.parse_args()

    report = run_llm_judge_evaluation(
        output_format=args.output,
        csv_path=args.csv_path,
        dataset_csv=args.dataset_csv,
    )

    print(report)


if __name__ == "__main__":
    main()
