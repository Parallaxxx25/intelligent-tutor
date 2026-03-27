"""
Unit tests for custom SQL tutoring tools.

Tests cover:
  - SQLExecutorTool: security validation (blocked DDL/DML)
  - SQLErrorClassifierTool: all SQL-specific categories
  - SQLHintGeneratorTool: levels 1-4 + no_error case (LLM mocked)

Note: SQL execution tests (execute_sql, run_sql_tests) require a
running PostgreSQL instance. Use `docker-compose up -d` first.

Version: 2026-03-27 (LLM-powered hint generator)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.tools.code_executor import execute_sql
from backend.tools.error_classifier import classify_sql_error
from backend.tools.hint_generator import generate_sql_hint


# ===================================================================
# SQL Executor — Security checks (no database needed)
# ===================================================================


class TestSQLExecutorSecurity:
    """Security validation tests for execute_sql."""

    def test_blocks_drop_table(self) -> None:
        """DROP TABLE is rejected."""
        result = execute_sql("DROP TABLE employees")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_blocks_insert(self) -> None:
        """INSERT is rejected."""
        result = execute_sql("INSERT INTO employees (name) VALUES ('hacker')")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_blocks_update(self) -> None:
        """UPDATE is rejected."""
        result = execute_sql("UPDATE employees SET salary = 0")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_blocks_delete(self) -> None:
        """DELETE is rejected."""
        result = execute_sql("DELETE FROM employees")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_blocks_alter(self) -> None:
        """ALTER TABLE is rejected."""
        result = execute_sql("ALTER TABLE employees ADD COLUMN hack TEXT")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_blocks_create(self) -> None:
        """CREATE TABLE is rejected."""
        result = execute_sql("CREATE TABLE evil (id INT)")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_blocks_truncate(self) -> None:
        """TRUNCATE is rejected."""
        result = execute_sql("TRUNCATE employees")
        assert result["success"] is False
        assert result["error_type"] == "security_violation"

    def test_allows_select(self) -> None:
        """SELECT passes security checks (may fail on connection)."""
        result = execute_sql("SELECT 1 AS test")
        # If DB is offline, it'll fail with a connection error, not security
        if not result["success"]:
            assert result["error_type"] != "security_violation"

    def test_allows_with_cte(self) -> None:
        """WITH (CTE) passes security checks."""
        result = execute_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")
        if not result["success"]:
            assert result["error_type"] != "security_violation"


# ===================================================================
# SQL Error Classifier
# ===================================================================


class TestSQLErrorClassifier:
    """Tests for classify_sql_error helper function."""

    def test_no_error(self) -> None:
        """All tests passed — no error."""
        result = classify_sql_error(all_tests_passed=True)
        assert result.error_type == "no_error"
        assert result.severity == "low"

    def test_syntax_error(self) -> None:
        """Syntax error in SQL."""
        result = classify_sql_error(
            error_message="",
            student_query="SELCT * FROM users",
            all_tests_passed=False,
        )
        assert result.error_type == "syntax_error"

    def test_column_error(self) -> None:
        """Column does not exist."""
        result = classify_sql_error(
            error_message='ERROR: column "employee_name" does not exist',
            all_tests_passed=False,
        )
        assert result.error_type == "column_error"
        assert result.problematic_clause == "SELECT"

    def test_relation_error(self) -> None:
        """Table does not exist."""
        result = classify_sql_error(
            error_message='ERROR: relation "employes" does not exist',
            all_tests_passed=False,
        )
        assert result.error_type == "relation_error"
        assert result.problematic_clause == "FROM"

    def test_join_error(self) -> None:
        """Missing FROM-clause entry."""
        result = classify_sql_error(
            error_message='ERROR: missing FROM-clause entry for table "d"',
            all_tests_passed=False,
        )
        assert result.error_type == "join_error"
        assert result.problematic_clause == "JOIN"

    def test_aggregation_error(self) -> None:
        """GROUP BY error."""
        result = classify_sql_error(
            error_message='ERROR: column "e.name" must appear in the GROUP BY clause',
            all_tests_passed=False,
        )
        assert result.error_type == "aggregation_error"
        assert result.problematic_clause == "GROUP BY"

    def test_ambiguity_error(self) -> None:
        """Ambiguous column."""
        result = classify_sql_error(
            error_message='ERROR: column reference "id" is ambiguous',
            all_tests_passed=False,
        )
        assert result.error_type == "ambiguity_error"

    def test_subquery_error(self) -> None:
        """Subquery returns multiple rows."""
        result = classify_sql_error(
            error_message="ERROR: more than one row returned by a subquery",
            all_tests_passed=False,
        )
        assert result.error_type == "subquery_error"
        assert result.problematic_clause == "subquery"

    def test_type_error(self) -> None:
        """Type mismatch."""
        result = classify_sql_error(
            error_message="ERROR: invalid input syntax for type integer",
            all_tests_passed=False,
        )
        assert result.error_type == "type_error"

    def test_timeout_error(self) -> None:
        """Statement timeout."""
        result = classify_sql_error(
            error_message="ERROR: canceling statement due to statement timeout",
            all_tests_passed=False,
        )
        assert result.error_type == "timeout_error"
        assert result.severity == "high"

    def test_logic_error(self) -> None:
        """Query runs but returns wrong results."""
        result = classify_sql_error(
            error_message="",
            all_tests_passed=False,
            failed_test_details="Row count mismatch — expected 3 rows, got 10 rows",
            student_query="SELECT * FROM employees WHERE salary > 50000",
        )
        assert result.error_type == "logic_error"
        assert result.problematic_clause == "WHERE"

    def test_logic_error_column_mismatch(self) -> None:
        """Logic error — wrong columns selected."""
        result = classify_sql_error(
            error_message="",
            all_tests_passed=False,
            failed_test_details="Column mismatch — expected ['name', 'salary'], got ['id', 'name']",
        )
        assert result.error_type == "logic_error"
        assert result.problematic_clause == "SELECT"

    def test_security_violation(self) -> None:
        """Security violation from executor."""
        result = classify_sql_error(
            error_message="forbidden",
            error_type_hint="security_violation",
            all_tests_passed=False,
        )
        assert result.error_type == "security_violation"
        assert result.severity == "high"


# ===================================================================
# SQL Hint Generator (LLM-powered, with mock)
# ===================================================================


def _mock_llm_response(hint_level: int, error_type: str, **kwargs):
    """Return a mock LLM structured response matching what the LLM would produce."""
    responses = {
        1: {
            "hint_text": "Take a closer look at your JOIN clause. Can you spot what might be missing?",
            "pedagogical_rationale": "Directing attention to the problematic clause.",
            "follow_up_question": "What does your JOIN clause do exactly?",
        },
        2: {
            "hint_text": "You have a GROUP BY / aggregation error. Every column in SELECT must be in GROUP BY or an aggregate.",
            "pedagogical_rationale": "Explaining the SQL concept behind the error.",
            "follow_up_question": "Which columns in your SELECT are not aggregated?",
        },
        3: {
            "hint_text": (
                "Here's a similar example:\n```sql\nSELECT dept, COUNT(*)\n"
                "FROM staff\nGROUP BY dept;\n```\nNotice every non-aggregated column is in GROUP BY."
            ),
            "pedagogical_rationale": "Showing a concept example without revealing the solution.",
            "follow_up_question": "Can you see how this pattern applies to your query?",
        },
        4: {
            "hint_text": (
                "Fill in the blanks:\n```sql\nSELECT ___\nFROM ___\n"
                "WHERE ___\nGROUP BY ___\n```"
            ),
            "pedagogical_rationale": "Providing a scaffold template.",
            "follow_up_question": "Which columns and tables do you need?",
        },
    }
    return responses.get(hint_level, responses[1])


class TestSQLHintGenerator:
    """Tests for generate_sql_hint helper function (LLM mocked)."""

    def test_no_error_congratulates(self) -> None:
        """When query is correct, congratulate the student (no LLM needed)."""
        result = generate_sql_hint(
            error_type="no_error",
            error_message="All tests passed",
            student_query="SELECT * FROM employees",
        )
        assert result["hint_level"] == 0
        assert (
            "great" in result["hint_text"].lower()
            or "correct" in result["hint_text"].lower()
        )

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_level_1_first_attempt(self, mock_llm) -> None:
        """First attempt → Level 1 hint via LLM."""
        mock_llm.return_value = {
            "hint_level": 1,
            "hint_type": "text",
            "hint_text": "Take a closer look at your JOIN clause. Something seems off.",
            "pedagogical_rationale": "Directing attention to the problematic clause.",
            "follow_up_question": "What does your JOIN clause do exactly?",
        }
        result = generate_sql_hint(
            error_type="join_error",
            error_message="missing FROM-clause",
            student_query="SELECT * FROM orders, customers",
            attempt_count=1,
            problematic_clause="JOIN",
        )
        assert result["hint_level"] == 1
        mock_llm.assert_called_once()

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_level_2_second_attempt(self, mock_llm) -> None:
        """Second attempt → Level 2 hint via LLM."""
        mock_llm.return_value = {
            "hint_level": 2,
            "hint_type": "text",
            "hint_text": "You have a GROUP BY / aggregation error. Every column in SELECT must be in GROUP BY or an aggregate.",
            "pedagogical_rationale": "Explaining the SQL concept.",
            "follow_up_question": "Which columns need GROUP BY?",
        }
        result = generate_sql_hint(
            error_type="aggregation_error",
            error_message="must appear in GROUP BY",
            student_query="SELECT name, COUNT(*) FROM employees",
            attempt_count=2,
            problematic_clause="GROUP BY",
        )
        assert result["hint_level"] == 2
        mock_llm.assert_called_once()

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_level_3_third_attempt(self, mock_llm) -> None:
        """Third attempt → Level 3 hint via LLM."""
        mock_llm.return_value = {
            "hint_level": 3,
            "hint_type": "example",
            "hint_text": "Here's a similar example with GROUP BY...",
            "pedagogical_rationale": "Concept example.",
            "follow_up_question": "See the pattern?",
        }
        result = generate_sql_hint(
            error_type="logic_error",
            error_message="Wrong output",
            student_query="SELECT * FROM employees WHERE salary > 1000",
            attempt_count=3,
        )
        assert result["hint_level"] == 3
        assert result["hint_type"] == "example"
        mock_llm.assert_called_once()

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_level_4_fourth_attempt(self, mock_llm) -> None:
        """Fourth attempt → Level 4 hint via LLM."""
        mock_llm.return_value = {
            "hint_level": 4,
            "hint_type": "code_template",
            "hint_text": "Fill in ___:\n```sql\nSELECT ___\nFROM ___\n```",
            "pedagogical_rationale": "Scaffold template.",
            "follow_up_question": "Start with SELECT.",
        }
        result = generate_sql_hint(
            error_type="logic_error",
            error_message="Wrong output",
            student_query="SELECT * FROM employees",
            attempt_count=4,
        )
        assert result["hint_level"] == 4
        assert result["hint_type"] == "code_template"
        mock_llm.assert_called_once()

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_llm_fallback_on_error(self, mock_llm) -> None:
        """When LLM fails, falls back to rule-based hints."""
        mock_llm.side_effect = RuntimeError("LLM unavailable")
        result = generate_sql_hint(
            error_type="join_error",
            error_message="missing FROM-clause",
            student_query="SELECT * FROM orders, customers",
            attempt_count=1,
            problematic_clause="JOIN",
        )
        # Should still produce a valid hint via fallback
        assert result["hint_level"] == 1
        assert len(result["hint_text"]) > 20
        assert "JOIN" in result["hint_text"]

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_level_1_logic_error_no_clause(self, mock_llm) -> None:
        """Logic error without specific clause still gives a useful hint via LLM."""
        mock_llm.return_value = {
            "hint_level": 1,
            "hint_type": "text",
            "hint_text": "Your query runs but produces unexpected results. Try re-reading the problem statement.",
            "pedagogical_rationale": "Attention nudge for logic error.",
            "follow_up_question": "What condition might be missing?",
        }
        result = generate_sql_hint(
            error_type="logic_error",
            error_message="Row count mismatch",
            student_query="SELECT * FROM employees",
            attempt_count=1,
            problematic_clause=None,
        )
        assert result["hint_level"] == 1
        assert len(result["hint_text"]) > 20

    @patch("backend.tools.hint_generator._generate_hint_with_llm")
    def test_timeout_hint(self, mock_llm) -> None:
        """Timeout error gives performance-related hint via LLM."""
        mock_llm.return_value = {
            "hint_level": 1,
            "hint_type": "text",
            "hint_text": "Your query is taking too long. Check your FROM clause — you may have an accidental Cartesian product.",
            "pedagogical_rationale": "Directing attention to performance issue.",
            "follow_up_question": "How many tables are you joining?",
        }
        result = generate_sql_hint(
            error_type="timeout_error",
            error_message="Statement timed out",
            student_query="SELECT * FROM orders, products",
            attempt_count=1,
            problematic_clause="FROM",
        )
        assert result["hint_level"] == 1
        lower_text = result["hint_text"].lower()
        assert (
            "from" in lower_text
            or "long" in lower_text
            or "timeout" in lower_text
            or "cartesian" in lower_text
        )

    def test_fallback_level_2_content(self) -> None:
        """Verify rule-based fallback produces correct level 2 content."""
        from backend.tools.hint_generator import _generate_hint_rulebased

        result = _generate_hint_rulebased(
            error_type="aggregation_error",
            error_message="must appear in GROUP BY",
            student_query="SELECT name, COUNT(*) FROM employees",
            hint_level=2,
            problem_description="",
            problematic_clause="GROUP BY",
        )
        assert result["hint_level"] == 2
        assert "group by" in result["hint_text"].lower()

    def test_fallback_level_4_has_blanks(self) -> None:
        """Verify rule-based fallback level 4 has fill-in-the-blanks."""
        from backend.tools.hint_generator import _generate_hint_rulebased

        result = _generate_hint_rulebased(
            error_type="logic_error",
            error_message="Wrong output",
            student_query="SELECT * FROM employees",
            hint_level=4,
            problem_description="",
            problematic_clause=None,
        )
        assert result["hint_level"] == 4
        assert result["hint_type"] == "code_template"
        assert "___" in result["hint_text"]
