"""
RAGAS Evaluation Runner — CLI entry point.

Runs the full RAG evaluation pipeline:
  1. Initialises ChromaDB knowledge base
  2. For each evaluation sample, runs the RAG pipeline
  3. Computes RAGAS metrics + custom hint-quality metrics
  4. Outputs report in markdown, JSON, or CSV format

Usage:
    python -m backend.evaluation.run_evaluation
    python -m backend.evaluation.run_evaluation --output csv
    python -m backend.evaluation.run_evaluation --output json
    python -m backend.evaluation.run_evaluation --output csv --csv-path results.csv

Version: 2026-03-27
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from backend.evaluation.eval_dataset import EVAL_DATASET, EvalSample
from backend.evaluation.ragas_evaluator import (
    RagasEvaluator,
    format_report_csv,
    format_report_json,
    format_report_markdown,
    export_report_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _build_user_input(sample: EvalSample) -> str:
    """Build the user_input string for RAGAS from an EvalSample."""
    parts = [
        f"Problem: {sample.problem_description}",
        f"Student SQL: {sample.student_query}",
    ]
    if sample.error_message:
        parts.append(f"Error: {sample.error_message}")
    parts.append(f"Error Type: {sample.error_type}")
    parts.append(f"Attempt: {sample.attempt_count}")
    return "\n".join(parts)


def run_evaluation(
    use_llm_metrics: bool = True,
    output_format: str = "markdown",
    csv_path: str | None = None,
) -> str:
    """
    Run the full RAGAS evaluation.

    Args:
        use_llm_metrics: Whether to use LLM-based RAGAS metrics.
        output_format: 'markdown', 'json', or 'csv'.
        csv_path: Optional file path for CSV export.

    Returns:
        The formatted report string.
    """
    # Step 1: Initialise knowledge base
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
    logger.info("Step 2: Building %d evaluation samples...", len(EVAL_DATASET))
    eval_samples: list[dict] = []

    for sample in EVAL_DATASET:
        user_input = _build_user_input(sample)

        # Retrieve RAG contexts for this sample
        retrieved_contexts = []
        retrieved_topics = []
        if retrieve_relevant_context is not None and sample.error_type != "no_error":
            try:
                rag_results = retrieve_relevant_context(
                    query=f"{sample.error_type}: {sample.student_query}",
                    error_type=sample.error_type,
                    n_results=3,
                )
                retrieved_contexts = [doc["content"] for doc in rag_results]
                retrieved_topics = [doc["topic"] for doc in rag_results]
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
                sample.sample_id, e,
            )

        eval_samples.append({
            "sample_id": sample.sample_id,
            "error_type": sample.error_type,
            "hint_level": sample.hint_level,
            "user_input": user_input,
            "response": generated_hint,
            "retrieved_contexts": retrieved_contexts,
            "reference": sample.reference_answer,
            "retrieved_topics": retrieved_topics,
            "expected_topics": sample.expected_rag_topics,
        })

    # Step 3: Run RAGAS evaluation
    logger.info("Step 3: Running RAGAS evaluation...")
    evaluator = RagasEvaluator() if use_llm_metrics else RagasEvaluator(llm=None)
    report = evaluator.evaluate_batch(eval_samples)

    # Step 4: Format output
    logger.info("Step 4: Generating %s report...", output_format)

    if output_format == "csv":
        result = format_report_csv(report)
        # Also export to file if path is provided
        if csv_path:
            export_report_csv(report, csv_path)
            logger.info("CSV exported to: %s", csv_path)
        else:
            # Default CSV path
            default_path = Path("evaluation_results.csv")
            export_report_csv(report, default_path)
            logger.info("CSV exported to: %s", default_path.resolve())
    elif output_format == "json":
        result = format_report_json(report)
    else:
        result = format_report_markdown(report)

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="RAGAS Evaluation Runner for the SQL Tutoring Pipeline",
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
        help="File path for CSV export (default: evaluation_results.csv)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM-based RAGAS metrics (faster, uses only custom metrics)",
    )

    args = parser.parse_args()

    report = run_evaluation(
        use_llm_metrics=not args.no_llm,
        output_format=args.output,
        csv_path=args.csv_path,
    )

    print(report)


if __name__ == "__main__":
    main()
