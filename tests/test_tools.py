"""
Unit tests for custom SQL tutoring tools.

Tests cover:
  - SQLExecutorTool: security validation (blocked DDL/DML)
  - SQLErrorClassifierTool: all SQL-specific categories
  - SQLHintGeneratorTool: levels 1-4 + no_error case

Note: SQL execution tests (execute_sql, run_sql_tests) require a
running PostgreSQL instance. Use `docker-compose up -d` first.

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

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
            error_message='ERROR: syntax error at or near "SELCT"',
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
# SQL Hint Generator
# ===================================================================

class TestSQLHintGenerator:
    """Tests for generate_sql_hint helper function."""

    def test_no_error_congratulates(self) -> None:
        """When query is correct, congratulate the student."""
        result = generate_sql_hint(
            error_type="no_error",
            error_message="All tests passed",
            student_query="SELECT * FROM employees",
        )
        assert result["hint_level"] == 0
        assert "great" in result["hint_text"].lower() or "correct" in result["hint_text"].lower()

    def test_level_1_first_attempt(self) -> None:
        """First attempt → Level 1 hint pointing to clause."""
        result = generate_sql_hint(
            error_type="join_error",
            error_message="missing FROM-clause",
            student_query="SELECT * FROM orders, customers",
            attempt_count=1,
            problematic_clause="JOIN",
        )
        assert result["hint_level"] == 1
        assert "JOIN" in result["hint_text"]

    def test_level_2_second_attempt(self) -> None:
        """Second attempt → Level 2 hint explaining the SQL concept."""
        result = generate_sql_hint(
            error_type="aggregation_error",
            error_message="must appear in GROUP BY",
            student_query="SELECT name, COUNT(*) FROM employees",
            attempt_count=2,
            problematic_clause="GROUP BY",
        )
        assert result["hint_level"] == 2
        assert "group by" in result["hint_text"].lower()

    def test_level_3_third_attempt(self) -> None:
        """Third attempt → Level 3 hint with SQL example."""
        result = generate_sql_hint(
            error_type="logic_error",
            error_message="Wrong output",
            student_query="SELECT * FROM employees WHERE salary > 1000",
            attempt_count=3,
        )
        assert result["hint_level"] == 3
        assert result["hint_type"] == "example"

    def test_level_4_fourth_attempt(self) -> None:
        """Fourth attempt → Level 4 hint with SQL template."""
        result = generate_sql_hint(
            error_type="logic_error",
            error_message="Wrong output",
            student_query="SELECT * FROM employees",
            attempt_count=4,
        )
        assert result["hint_level"] == 4
        assert result["hint_type"] == "code_template"
        assert "___" in result["hint_text"]

    def test_level_1_logic_error_no_clause(self) -> None:
        """Logic error without specific clause still gives a useful hint."""
        result = generate_sql_hint(
            error_type="logic_error",
            error_message="Row count mismatch",
            student_query="SELECT * FROM employees",
            attempt_count=1,
            problematic_clause=None,
        )
        assert result["hint_level"] == 1
        assert len(result["hint_text"]) > 20

    def test_timeout_hint(self) -> None:
        """Timeout error gives performance-related hint."""
        result = generate_sql_hint(
            error_type="timeout_error",
            error_message="Statement timed out",
            student_query="SELECT * FROM orders, products",
            attempt_count=1,
            problematic_clause="FROM",
        )
        assert result["hint_level"] == 1
        lower_text = result["hint_text"].lower()
        # When a specific clause is identified, the hint directs attention there
        assert "from" in lower_text or "long" in lower_text or "timeout" in lower_text
