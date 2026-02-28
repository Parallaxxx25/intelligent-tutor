"""
Tests for CrewAI Pipeline — run_pipeline_crewai().

Tests cover:
  - All-tests-passed fast path
  - CrewAI tutoring pipeline fallback on failure

Version: 2026-02-27
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.db.schemas import CodeSubmission


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_submission():
    """A sample student SQL submission."""
    return CodeSubmission(
        user_id=1,
        problem_id=1,
        code="SELECT name FROM employee WHERE salary > 50000;",
        language="sql",
    )


@pytest.fixture
def sample_test_cases():
    """Sample test cases with gold-standard queries."""
    return [
        {
            "test_case_id": 1,
            "input_data": "SELECT name FROM employees WHERE salary > 50000",
            "expected_output": "",
        },
    ]


@pytest.fixture
def mock_grading_failed():
    """Mocked grading result for a failed submission."""
    return {
        "passed": False,
        "score": 0.0,
        "total_tests": 1,
        "passed_tests": 0,
        "test_results": [
            {
                "test_case_id": 1,
                "passed": False,
                "error_message": 'relation "employee" does not exist',
                "expected_columns": ["name"],
                "actual_columns": None,
                "expected_row_count": 3,
                "actual_row_count": None,
            }
        ],
        "student_error": 'relation "employee" does not exist',
        "student_error_type": "relation_error",
    }


@pytest.fixture
def mock_grading_passed():
    """Mocked grading result for a passing submission."""
    return {
        "passed": True,
        "score": 1.0,
        "total_tests": 1,
        "passed_tests": 1,
        "test_results": [
            {
                "test_case_id": 1,
                "passed": True,
                "error_message": None,
                "expected_columns": ["name"],
                "actual_columns": ["name"],
                "expected_row_count": 3,
                "actual_row_count": 3,
            }
        ],
        "student_error": None,
        "student_error_type": None,
    }

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCrewAIPipelinePassingSubmission:
    """Test the fast path when all tests pass in CrewAI pipeline."""

    @patch("backend.agents.supervisor.run_sql_tests")
    def test_all_tests_passed_returns_congrats(
        self, mock_tests, sample_submission, sample_test_cases, mock_grading_passed
    ):
        """When all tests pass, the pipeline should return congratulations without calling CrewAI."""
        from backend.agents.supervisor import run_pipeline_crewai

        mock_tests.return_value = mock_grading_passed

        print("\n" + "=" * 70)
        print("  TEST: All Tests Passed → Fast Path (no CrewAI)")
        print("=" * 70)

        print("\n📥 INPUT — Student Submission:")
        print(f"   User ID      : {sample_submission.user_id}")
        print(f"   Problem ID   : {sample_submission.problem_id}")
        print(f"   SQL Code     : {sample_submission.code}")
        print(f"   Language     : {sample_submission.language}")

        print("\n📋 INPUT — Test Cases:")
        for i, tc in enumerate(sample_test_cases):
            print(f"   Test {i+1}: {json.dumps(tc, indent=6)}")

        result = run_pipeline_crewai(
            submission=sample_submission,
            problem_description="Test problem",
            problem_topic="basics",
            test_cases=sample_test_cases,
            attempt_count=1,
        )

        print("\n" + "-" * 70)
        print("📊 STAGE 1 — Grading Result:")
        print(f"   Passed       : {result.grading.passed}")
        print(f"   Score        : {result.grading.score}")
        print(f"   Total Tests  : {result.grading.total_tests}")
        print(f"   Passed Tests : {result.grading.passed_tests}")

        print("\n🔍 STAGE 2 — Diagnosis:")
        print(f"   Skipped (all tests passed)")

        print("\n🎓 STAGE 3 — Hint Output:")
        print(f"   Hint Level   : {result.hint.hint_level}")
        print(f"   Hint Type    : {result.hint.hint_type}")
        print(f"   Hint Text    : {result.hint.hint_text}")
        print(f"   Rationale    : {result.hint.pedagogical_rationale}")
        print(f"   Follow-up    : {result.hint.follow_up_question}")

        print("\n✅ FINAL RESULT:")
        print(f"   Overall Passed : {result.overall_passed}")
        print(f"   Timestamp      : {result.timestamp}")
        print("=" * 70)

        assert result.overall_passed is True
        assert result.grading.passed is True
        assert result.diagnosis is None
        assert "great job" in result.hint.hint_text.lower()


class TestCrewAIPipelineFallback:
    """Test that CrewAI invokes the tutoring agents correctly on failure."""

    @patch("backend.agents.supervisor.classify_sql_error")
    @patch("backend.agents.supervisor.TutoringCrew")
    @patch("backend.agents.supervisor.run_sql_tests")
    def test_crewai_diagnoses_and_tutors(
        self,
        mock_tests,
        mock_crew_class,
        mock_classifier,
        sample_submission,
        sample_test_cases,
        mock_grading_failed,
    ):
        """When tests fail, CrewAI should kick off."""
        from backend.agents.supervisor import run_pipeline_crewai

        mock_tests.return_value = mock_grading_failed

        # Mock the deterministic classifier output since CrewAI needs it mapped
        mock_classifier_result = MagicMock()
        mock_classifier_result.error_type = "relation_error"
        mock_classifier_result.error_message = 'relation "employee" does not exist'
        mock_classifier_result.problematic_clause = "FROM"
        mock_classifier_result.severity = "medium"
        mock_classifier.return_value = mock_classifier_result

        # Mock the crew kickoff
        mock_crew_instance = MagicMock()
        mock_crew_class.return_value = mock_crew_instance
        mock_crew_instance.kickoff.return_value = (
            "🔍 It looks like you're referencing a table called 'employee', "
            "but the correct table name is 'employees' (with an 's'). "
            "Check your FROM clause! Can you spot the difference?"
        )

        print("\n" + "=" * 70)
        print("  TEST: Failed Submission → CrewAI Diagnosis + Tutoring")
        print("=" * 70)

        print("\n📥 INPUT — Student Submission:")
        print(f"   User ID      : {sample_submission.user_id}")
        print(f"   Problem ID   : {sample_submission.problem_id}")
        print(f"   SQL Code     : {sample_submission.code}")
        print(f"   Language     : {sample_submission.language}")

        print("\n📋 INPUT — Test Cases:")
        for i, tc in enumerate(sample_test_cases):
            print(f"   Test {i+1}: {json.dumps(tc, indent=6)}")

        result = run_pipeline_crewai(
            submission=sample_submission,
            problem_description="Select employee names",
            problem_topic="SELECT basics",
            test_cases=sample_test_cases,
            attempt_count=1,
        )

        print("\n" + "-" * 70)
        print("📊 STAGE 1 — Grading Result:")
        print(f"   Passed       : {result.grading.passed}")
        print(f"   Score        : {result.grading.score}")
        print(f"   Total Tests  : {result.grading.total_tests}")
        print(f"   Passed Tests : {result.grading.passed_tests}")
        print(f"   Student Error: {result.grading.student_error}")
        print(f"   Error Type   : {result.grading.student_error_type}")
        for i, tr in enumerate(result.grading.test_results):
            print(f"   Test Result {i+1}:")
            print(f"     passed          : {tr.passed}")
            print(f"     error_message   : {tr.error_message}")
            print(f"     expected_columns: {tr.expected_columns}")
            print(f"     actual_columns  : {tr.actual_columns}")

        print("\n🔍 STAGE 2 — Diagnosis (Rule-based classifier → CrewAI context):")
        print(f"   Error Type         : {result.diagnosis.error_type}")
        print(f"   Error Message      : {result.diagnosis.error_message}")
        print(f"   Problematic Clause : {result.diagnosis.problematic_clause}")
        print(f"   Severity           : {result.diagnosis.severity}")
        print(f"   Hint Level         : {result.diagnosis.recommended_hint_level}")
        print(f"   Rationale          : {result.diagnosis.pedagogical_rationale}")

        print("\n🤖 STAGE 3 — CrewAI TutoringCrew Kickoff:")
        print(f"   Crew was invoked   : {mock_crew_instance.kickoff.called}")
        print(f"   Kickoff call count : {mock_crew_instance.kickoff.call_count}")
        kickoff_args = mock_crew_instance.kickoff.call_args
        if kickoff_args:
            print(f"   Kickoff kwargs     :")
            for k, v in kickoff_args.kwargs.items():
                val_str = str(v)
                if len(val_str) > 80:
                    val_str = val_str[:80] + "..."
                print(f"     {k}: {val_str}")

        print("\n🎓 STAGE 4 — Hint Output (from CrewAI):")
        print(f"   Hint Level   : {result.hint.hint_level}")
        print(f"   Hint Type    : {result.hint.hint_type}")
        print(f"   Hint Text    : {result.hint.hint_text}")
        print(f"   Rationale    : {result.hint.pedagogical_rationale}")
        print(f"   Follow-up    : {result.hint.follow_up_question}")

        print("\n✅ FINAL RESULT:")
        print(f"   Overall Passed : {result.overall_passed}")
        print(f"   Timestamp      : {result.timestamp}")
        print("=" * 70)

        assert result.overall_passed is False
        assert result.diagnosis is not None
        assert result.diagnosis.error_type == "relation_error"

        # Check hint population
        assert "employee" in result.hint.hint_text.lower()

        # Verify kickoff was called on the crew
        mock_crew_instance.kickoff.assert_called_once()
