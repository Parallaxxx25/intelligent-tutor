"""
Tests for RAGAS Evaluation Module.

Tests cover:
  - EvalDataset structure and coverage
  - Custom hint-quality metrics (hint level compliance, no solution leakage)
  - RagasEvaluator (with mocked LLM)
  - Report formatters (markdown, JSON, CSV)
  - Error taxonomy coverage validation

All tests use mocked LLM calls for deterministic execution.

Version: 2026-03-27
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.evaluation.eval_dataset import (
    EVAL_DATASET,
    EvalSample,
    get_error_type_coverage,
    get_hint_level_distribution,
)
from backend.evaluation.ragas_evaluator import (
    EvaluationReport,
    RagasEvaluator,
    SampleResult,
    export_report_csv,
    format_report_csv,
    format_report_json,
    format_report_markdown,
    score_hint_level_compliance,
    score_no_solution_leakage,
)


# ===================================================================
# TestEvalDataset — validate dataset structure and coverage
# ===================================================================


class TestEvalDataset:
    """Tests for the evaluation dataset."""

    def test_dataset_has_15_samples(self):
        """Dataset should contain exactly 15 samples."""
        assert len(EVAL_DATASET) == 15

    def test_all_samples_are_eval_sample_instances(self):
        """Every item should be an EvalSample dataclass."""
        for sample in EVAL_DATASET:
            assert isinstance(sample, EvalSample)

    def test_all_sample_ids_unique(self):
        """All sample_ids must be unique."""
        ids = [s.sample_id for s in EVAL_DATASET]
        assert len(ids) == len(set(ids))

    def test_error_taxonomy_complete(self):
        """Dataset should cover all 11 error taxonomy categories."""
        expected_types = {
            "syntax_error",
            "column_error",
            "relation_error",
            "join_error",
            "aggregation_error",
            "subquery_error",
            "type_error",
            "logic_error",
            "ambiguity_error",
            "timeout_error",
            "no_error",
        }
        coverage = get_error_type_coverage()
        actual_types = set(coverage.keys())
        assert expected_types == actual_types, (
            f"Missing error types: {expected_types - actual_types}"
        )

    def test_error_type_coverage_counts(self):
        """Each error type should appear at least once."""
        coverage = get_error_type_coverage()
        for error_type, count in coverage.items():
            assert count >= 1, f"{error_type} has no samples"

    def test_hint_levels_1_through_4_present(self):
        """Hint levels 0–4 should all be represented."""
        dist = get_hint_level_distribution()
        for level in [0, 1, 2, 3, 4]:
            assert level in dist, f"Hint level {level} missing from dataset"

    def test_all_samples_have_required_fields(self):
        """Every sample must have non-empty required fields."""
        for sample in EVAL_DATASET:
            assert sample.sample_id, f"Missing sample_id"
            assert sample.error_type, f"Missing error_type in {sample.sample_id}"
            assert sample.student_query, f"Missing student_query in {sample.sample_id}"
            assert sample.problem_description, f"Missing problem_description in {sample.sample_id}"
            assert sample.ground_truth_hint, f"Missing ground_truth_hint in {sample.sample_id}"

    def test_no_error_sample_has_level_zero(self):
        """The no_error sample should have hint_level = 0."""
        no_error = [s for s in EVAL_DATASET if s.error_type == "no_error"]
        assert len(no_error) >= 1
        for s in no_error:
            assert s.hint_level == 0

    def test_attempt_count_matches_hint_level(self):
        """Attempt count should follow the escalation policy."""
        for sample in EVAL_DATASET:
            if sample.error_type == "no_error":
                continue
            expected_level = (
                1 if sample.attempt_count <= 1
                else 2 if sample.attempt_count == 2
                else 3 if sample.attempt_count == 3
                else 4
            )
            assert sample.hint_level == expected_level, (
                f"{sample.sample_id}: attempt {sample.attempt_count} should be "
                f"level {expected_level}, got {sample.hint_level}"
            )


# ===================================================================
# TestHintQualityMetrics — custom hint-quality scoring
# ===================================================================


class TestHintLevelCompliance:
    """Tests for score_hint_level_compliance()."""

    def test_level_0_congratulatory(self):
        """Level 0 (no error) should score high for congratulatory text."""
        score = score_hint_level_compliance(
            "Great job! Your query is correct. Well done!", 0
        )
        assert score >= 0.5

    def test_level_0_non_congratulatory(self):
        """Level 0 with error message should score low."""
        score = score_hint_level_compliance(
            "You have a syntax error in your query.", 0
        )
        assert score <= 0.5

    def test_level_1_attention_no_code(self):
        """Level 1 should score high without code blocks."""
        score = score_hint_level_compliance(
            "Take a closer look at your SELECT clause. Can you spot the issue?", 1
        )
        assert score >= 0.8

    def test_level_1_penalised_for_code(self):
        """Level 1 should be penalised for showing code examples."""
        score = score_hint_level_compliance(
            "Here's an example:\n```sql\nSELECT a, b FROM t;\n```", 1
        )
        assert score < 0.8

    def test_level_3_with_code_example(self):
        """Level 3 should score high with a code example."""
        score = score_hint_level_compliance(
            "Here's a similar example:\n```sql\nSELECT * FROM employees;\n```", 3
        )
        assert score >= 0.8

    def test_level_3_without_code(self):
        """Level 3 without code should score low."""
        score = score_hint_level_compliance(
            "You should check the JOIN condition.", 3
        )
        assert score < 0.8

    def test_level_4_with_blanks(self):
        """Level 4 should score high with template blanks."""
        score = score_hint_level_compliance(
            "Fill in the blanks:\n```sql\nSELECT ___ FROM ___;\n```", 4
        )
        assert score >= 0.8

    def test_level_4_without_blanks(self):
        """Level 4 without blanks should score lower."""
        score = score_hint_level_compliance(
            "Just try rewriting your query from scratch.", 4
        )
        assert score < 0.8

    def test_scores_always_in_range(self):
        """All scores should be between 0.0 and 1.0."""
        for level in range(5):
            for hint in ["", "test", "```sql\n___ \n```", "Great job!"]:
                score = score_hint_level_compliance(hint, level)
                assert 0.0 <= score <= 1.0, f"Score {score} out of range for level {level}"


class TestNoSolutionLeakage:
    """Tests for score_no_solution_leakage()."""

    def test_no_reference_returns_perfect(self):
        """No reference answer means no leakage possible."""
        score = score_no_solution_leakage("any hint text", "")
        assert score == 1.0

    def test_exact_match_returns_zero(self):
        """Exact solution in hint should return 0.0."""
        ref = "SELECT first_name, last_name FROM sales.customers;"
        score = score_no_solution_leakage(
            f"Here's the answer: {ref}", ref
        )
        assert score == 0.0

    def test_no_overlap_returns_high(self):
        """No SQL overlap should return high score."""
        score = score_no_solution_leakage(
            "Check your comma usage in the SELECT clause.",
            "SELECT first_name, last_name FROM sales.customers;"
        )
        assert score >= 0.5

    def test_partial_overlap(self):
        """Partial overlap should return intermediate score."""
        score = score_no_solution_leakage(
            "Your query should use SELECT with FROM to fetch data.",
            "SELECT first_name, last_name FROM sales.customers;"
        )
        assert 0.0 <= score <= 1.0


# ===================================================================
# TestRagasEvaluator — evaluator with mocked LLM
# ===================================================================


class TestRagasEvaluator:
    """Tests for RagasEvaluator class."""

    def test_init_without_llm(self):
        """Evaluator should initialise without LLM."""
        evaluator = RagasEvaluator(llm=None, embeddings=None)
        assert evaluator.llm is None

    def test_evaluate_sample_custom_metrics_only(self):
        """Without LLM, custom metrics should still be computed."""
        evaluator = RagasEvaluator(llm=None, embeddings=None)
        scores = evaluator.evaluate_sample(
            user_input="SELECT * FROMM table;",
            response="Check your FROM keyword spelling.",
            retrieved_contexts=["SQL SELECT basics..."],
            reference="Use FROM, not FROMM.",
            expected_level=1,
        )
        assert scores["hint_level_compliance"] is not None
        assert scores["no_solution_leakage"] is not None
        assert scores["faithfulness"] is None  # No LLM
        assert scores["answer_relevancy"] is None

    def test_evaluate_batch_produces_report(self):
        """Batch evaluation should produce a complete report."""
        evaluator = RagasEvaluator(llm=None, embeddings=None)

        samples = [
            {
                "sample_id": "test_01",
                "error_type": "syntax_error",
                "hint_level": 1,
                "user_input": "SELECT * FROMM t;",
                "response": "Check your FROM clause.",
                "retrieved_contexts": ["SQL syntax guide..."],
                "reference": "Use FROM, not FROMM.",
            },
            {
                "sample_id": "test_02",
                "error_type": "join_error",
                "hint_level": 2,
                "user_input": "SELECT a, b FROM t1, t2;",
                "response": "You need a JOIN condition.",
                "retrieved_contexts": ["JOIN guide..."],
                "reference": "Use JOIN ON.",
            },
        ]

        report = evaluator.evaluate_batch(samples)

        assert isinstance(report, EvaluationReport)
        assert report.total_samples == 2
        assert len(report.sample_results) == 2
        assert report.error_types_covered == 2
        assert report.avg_hint_level_compliance > 0.0
        assert report.avg_no_solution_leakage > 0.0

    def test_evaluate_batch_with_all_dataset_samples(self):
        """Evaluate the full dataset (custom metrics only, no LLM)."""
        evaluator = RagasEvaluator(llm=None, embeddings=None)

        samples = [
            {
                "sample_id": s.sample_id,
                "error_type": s.error_type,
                "hint_level": s.hint_level,
                "user_input": f"{s.problem_description}\n{s.student_query}",
                "response": s.ground_truth_hint,
                "retrieved_contexts": [],
                "reference": s.reference_answer,
            }
            for s in EVAL_DATASET
        ]

        report = evaluator.evaluate_batch(samples)

        assert report.total_samples == 15
        assert report.error_types_covered == 11
        assert report.taxonomy_coverage_pct == 100.0


# ===================================================================
# TestReportFormatters — markdown, JSON, CSV output
# ===================================================================


class TestReportFormatters:
    """Tests for report formatting functions."""

    @pytest.fixture
    def sample_report(self) -> EvaluationReport:
        """Create a sample report for testing."""
        return EvaluationReport(
            timestamp="2026-03-27T12:00:00+00:00",
            total_samples=3,
            avg_faithfulness=0.85,
            avg_answer_relevancy=0.90,
            avg_context_precision=0.75,
            avg_context_recall=0.80,
            avg_hint_level_compliance=0.95,
            avg_no_solution_leakage=0.88,
            error_types_covered=3,
            error_types_total=11,
            taxonomy_coverage_pct=27.3,
            sample_results=[
                SampleResult(
                    sample_id="s1",
                    error_type="syntax_error",
                    hint_level=1,
                    faithfulness=0.90,
                    answer_relevancy=0.85,
                    context_precision=0.80,
                    context_recall=0.75,
                    hint_level_compliance=1.0,
                    no_solution_leakage=0.90,
                ),
                SampleResult(
                    sample_id="s2",
                    error_type="join_error",
                    hint_level=2,
                    faithfulness=0.80,
                    answer_relevancy=0.95,
                    context_precision=0.70,
                    context_recall=0.85,
                    hint_level_compliance=0.90,
                    no_solution_leakage=0.85,
                ),
                SampleResult(
                    sample_id="s3",
                    error_type="no_error",
                    hint_level=0,
                    faithfulness=None,
                    answer_relevancy=None,
                    context_precision=None,
                    context_recall=None,
                    hint_level_compliance=0.95,
                    no_solution_leakage=0.90,
                ),
            ],
        )

    def test_markdown_report_contains_header(self, sample_report):
        """Markdown report should have a title."""
        md = format_report_markdown(sample_report)
        assert "# RAGAS Evaluation Report" in md

    def test_markdown_report_contains_scores(self, sample_report):
        """Markdown report should contain aggregate scores."""
        md = format_report_markdown(sample_report)
        assert "Faithfulness" in md
        assert "0.850" in md
        assert "Answer Relevancy" in md

    def test_markdown_report_contains_taxonomy(self, sample_report):
        """Markdown report should show taxonomy coverage."""
        md = format_report_markdown(sample_report)
        assert "3 / 11" in md

    def test_markdown_report_per_sample_table(self, sample_report):
        """Markdown report should list per-sample results."""
        md = format_report_markdown(sample_report)
        assert "s1" in md
        assert "s2" in md
        assert "s3" in md
        assert "syntax_error" in md
        assert "N/A" in md  # For s3's None RAGAS scores

    def test_json_report_is_valid_json(self, sample_report):
        """JSON report should be valid JSON."""
        json_str = format_report_json(sample_report)
        data = json.loads(json_str)
        assert data["total_samples"] == 3
        assert data["aggregate_scores"]["faithfulness"] == 0.85
        assert len(data["sample_results"]) == 3

    def test_json_report_has_taxonomy_coverage(self, sample_report):
        """JSON report should contain taxonomy coverage."""
        json_str = format_report_json(sample_report)
        data = json.loads(json_str)
        assert data["taxonomy_coverage"]["covered"] == 3
        assert data["taxonomy_coverage"]["total"] == 11

    def test_csv_report_has_header(self, sample_report):
        """CSV report should have proper header row."""
        csv_str = format_report_csv(sample_report)
        reader = csv.reader(io.StringIO(csv_str))
        header = next(reader)
        assert "sample_id" in header
        assert "faithfulness" in header
        assert "hint_level_compliance" in header

    def test_csv_report_has_data_rows(self, sample_report):
        """CSV report should have one row per sample."""
        csv_str = format_report_csv(sample_report)
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)
        # Header + 3 data rows + blank + AVERAGE + blank + COVERAGE = 8
        data_rows = [r for r in rows if r and r[0] not in ("", "AVERAGE", "TAXONOMY_COVERAGE")]
        # Subtract header
        header = data_rows[0]
        sample_rows = data_rows[1:]
        assert len(sample_rows) == 3

    def test_csv_report_contains_average_row(self, sample_report):
        """CSV report should have an AVERAGE summary row."""
        csv_str = format_report_csv(sample_report)
        assert "AVERAGE" in csv_str

    def test_csv_report_contains_taxonomy_row(self, sample_report):
        """CSV report should have a TAXONOMY_COVERAGE row."""
        csv_str = format_report_csv(sample_report)
        assert "TAXONOMY_COVERAGE" in csv_str

    def test_csv_export_creates_file(self, sample_report):
        """export_report_csv should create a file on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test_results.csv"
            result = export_report_csv(sample_report, filepath)
            assert result.exists()
            content = result.read_text()
            assert "sample_id" in content
            assert "s1" in content

    def test_csv_export_nested_directory(self, sample_report):
        """export_report_csv should create parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "nested" / "dir" / "results.csv"
            result = export_report_csv(sample_report, filepath)
            assert result.exists()


# ===================================================================
# TestErrorTaxonomyCoverage — comprehensive taxonomy validation
# ===================================================================


class TestErrorTaxonomyCoverage:
    """Validate the error taxonomy is fully exercised."""

    FULL_TAXONOMY = {
        "syntax_error",
        "column_error",
        "relation_error",
        "join_error",
        "aggregation_error",
        "subquery_error",
        "type_error",
        "logic_error",
        "ambiguity_error",
        "timeout_error",
        "no_error",
    }

    def test_all_11_types_covered(self):
        """The dataset must cover all 11 error types."""
        covered = set(s.error_type for s in EVAL_DATASET)
        assert covered == self.FULL_TAXONOMY

    def test_error_types_match_classifier(self):
        """Error types in dataset should match the error_classifier taxonomy."""
        # These are the types defined in error_classifier.py
        classifier_types = {
            "syntax_error", "column_error", "relation_error",
            "join_error", "aggregation_error", "subquery_error",
            "type_error", "logic_error", "ambiguity_error",
            "timeout_error", "no_error",
        }
        dataset_types = set(s.error_type for s in EVAL_DATASET)
        assert dataset_types == classifier_types

    def test_each_hint_level_has_multiple_samples(self):
        """Error types with multiple samples test different hint levels."""
        multi_sample = get_error_type_coverage()
        types_with_multiple = {t for t, c in multi_sample.items() if c > 1}
        # We expect syntax_error, join_error, aggregation_error, logic_error
        assert len(types_with_multiple) >= 4

    def test_ground_truth_hints_are_non_trivial(self):
        """Ground truth hints should be substantial (>20 chars)."""
        for sample in EVAL_DATASET:
            assert len(sample.ground_truth_hint) > 20, (
                f"{sample.sample_id}: ground_truth_hint too short"
            )
