"""
Tests for LangGraph Pipeline — run_pipeline_langgraph().

Tests cover:
  - All-tests-passed fast path
  - LangGraph tutoring pipeline on failure

Version: 2026-03-20
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


class TestLangGraphPipelinePassingSubmission:
    """Test the fast path when all tests pass in LangGraph pipeline."""

    @patch("backend.agents.supervisor.run_sql_tests")
    def test_all_tests_passed_returns_congrats(
        self, mock_tests, sample_submission, sample_test_cases, mock_grading_passed
    ):
        """When all tests pass, the pipeline should return congratulations without invoking the graph."""
        from backend.agents.supervisor import run_pipeline_langgraph

        mock_tests.return_value = mock_grading_passed

        print("\n" + "=" * 70)
        print("  TEST: All Tests Passed → Fast Path (no LangGraph)")
        print("=" * 70)

        print("\n📥 INPUT — Student Submission:")
        print(f"   User ID      : {sample_submission.user_id}")
        print(f"   Problem ID   : {sample_submission.problem_id}")
        print(f"   SQL Code     : {sample_submission.code}")
        print(f"   Language     : {sample_submission.language}")

        print("\n📋 INPUT — Test Cases:")
        for i, tc in enumerate(sample_test_cases):
            print(f"   Test {i+1}: {json.dumps(tc, indent=6)}")

        result = run_pipeline_langgraph(
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


class TestLangGraphPipelineFallback:
    """Test that LangGraph invokes the tutoring graph correctly on failure."""

    @patch("backend.agents.supervisor.build_tutoring_graph")
    @patch("backend.agents.supervisor.run_sql_tests")
    def test_langgraph_diagnoses_and_tutors(
        self,
        mock_tests,
        mock_build_graph,
        sample_submission,
        sample_test_cases,
        mock_grading_failed,
    ):
        """When tests fail, LangGraph should invoke the graph."""
        from backend.agents.supervisor import run_pipeline_langgraph

        mock_tests.return_value = mock_grading_failed

        # Mock the compiled graph
        mock_compiled = MagicMock()
        mock_build_graph.return_value = mock_compiled
        mock_compiled.invoke.return_value = {
            "student_code": sample_submission.code,
            "grading_raw": mock_grading_failed,
            "diagnosis_error_type": "relation_error",
            "diagnosis_error_message": 'relation "employee" does not exist',
            "diagnosis_problematic_clause": "FROM",
            "diagnosis_severity": "medium",
            "recommended_hint_level": 1,
            "pedagogical_rationale": "Rule-based diagnosis. Attempt 1.",
            "hint_raw": {
                "hint_level": 1,
                "hint_type": "text",
                "hint_text": (
                    "🔍 It looks like you're referencing a table called 'employee', "
                    "but the correct table name is 'employees' (with an 's'). "
                    "Check your FROM clause! Can you spot the difference?"
                ),
                "pedagogical_rationale": "Level 1 (Attention): Directing attention to FROM clause.",
                "follow_up_question": "What does your FROM clause do exactly?",
            },
            "hint_text": (
                "🔍 It looks like you're referencing a table called 'employee', "
                "but the correct table name is 'employees' (with an 's'). "
                "Check your FROM clause! Can you spot the difference?"
            ),
        }

        print("\n" + "=" * 70)
        print("  TEST: Failed Submission → LangGraph Diagnosis + Tutoring")
        print("=" * 70)

        print("\n📥 INPUT — Student Submission:")
        print(f"   User ID      : {sample_submission.user_id}")
        print(f"   Problem ID   : {sample_submission.problem_id}")
        print(f"   SQL Code     : {sample_submission.code}")
        print(f"   Language     : {sample_submission.language}")

        print("\n📋 INPUT — Test Cases:")
        for i, tc in enumerate(sample_test_cases):
            print(f"   Test {i+1}: {json.dumps(tc, indent=6)}")

        result = run_pipeline_langgraph(
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

        print("\n🔍 STAGE 2 — Diagnosis (LangGraph graph output):")
        print(f"   Error Type         : {result.diagnosis.error_type}")
        print(f"   Error Message      : {result.diagnosis.error_message}")
        print(f"   Problematic Clause : {result.diagnosis.problematic_clause}")
        print(f"   Severity           : {result.diagnosis.severity}")
        print(f"   Hint Level         : {result.diagnosis.recommended_hint_level}")
        print(f"   Rationale          : {result.diagnosis.pedagogical_rationale}")

        print("\n🤖 STAGE 3 — LangGraph Graph Invocation:")
        print(f"   Graph invoked      : {mock_compiled.invoke.called}")
        print(f"   Invoke call count  : {mock_compiled.invoke.call_count}")

        print("\n🎓 STAGE 4 — Hint Output (from LangGraph):")
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

        # Verify graph was invoked
        mock_compiled.invoke.assert_called_once()

# usage python -m pytest tests/test_langgraph_pipeline.py -s -k "TestLangGraphStateTransitions"
class TestLangGraphStateTransitions:
    """Test class that captures and prints the intermediate states in the LangGraph pipeline."""

    def test_state_transitions_like_script(self):
        """Replicates print_state_transitions.py by running the real LangGraph graph."""
        from backend.agents.supervisor import build_tutoring_graph
        from pprint import pprint

        print("\n" + "=" * 70)
        print("  TEST: LangGraph Pipeline State Transitions")
        print("=" * 70)

        initial_state = {
            "student_code": "SELECT * FROM employes;",
            "grading_raw": {
                "passed": False,
                "score": 0.0,
                "total_tests": 1,
                "passed_tests": 0,
                "test_results": [
                    {
                        "test_case_id": 1,
                        "passed": False,
                        "error_message": 'relation "employes" does not exist',
                        "expected_columns": ["id", "name"],
                        "actual_columns": None,
                        "expected_row_count": 5,
                        "actual_row_count": None,
                    }
                ],
                "student_error": 'relation "employes" does not exist',
                "student_error_type": "relation_error",
            },
            "grading_results_str": "Test failed: relation 'employes' does not exist",
            "attempt_count": 1,
            "problem_description": "Select all employees from the database.",
            "problem_topic": "SELECT statement",
        }

        print("\n[INITIAL STATE] Passed to Graph:")
        pprint(initial_state)
        print("-" * 60)

        graph = build_tutoring_graph()

        print("\n[STARTING GRAPH EXECUTION]")
        nodes_executed = []
        for event in graph.stream(initial_state):
            for node_name, node_state_updates in event.items():
                nodes_executed.append(node_name)
                print(f"\n---> [NODE EXECUTED]: {node_name.upper()}")
                print("State updates generated by this node:")

                printable_updates = {}
                for k, v in node_state_updates.items():
                    if k == "classification":
                        printable_updates[k] = "<ClassificationObject>"
                    else:
                        printable_updates[k] = v

                pprint(printable_updates)
                print("-" * 60)

        print("\n[GRAPH EXECUTION COMPLETE]")

        # Verify the key nodes were executed in the pipeline
        assert "diagnose" in nodes_executed
        assert "tutor" in nodes_executed
