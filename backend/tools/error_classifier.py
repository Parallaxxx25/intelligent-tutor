"""
SQL Error Classifier Tool — SQL-specific error taxonomy.

Classifies SQL query errors into pedagogical categories:
  - syntax_error      : Malformed SQL (missing keywords, bad structure)
  - column_error      : Wrong / misspelled column name
  - relation_error    : Wrong / misspelled table name
  - join_error        : Incorrect or missing JOIN condition
  - aggregation_error : GROUP BY / HAVING misuse, missing aggregation
  - subquery_error    : Subquery returns wrong shape or is malformed
  - type_error        : Data-type mismatch in comparison or function
  - logic_error       : Query runs but returns wrong result set
  - ambiguity_error   : Ambiguous column reference in a multi-table query
  - timeout_error     : Query exceeds time limit (inefficient scan, etc.)
  - no_error          : All tests pass

Version: 2026-02-12  (SQL-focused rewrite)
"""

from __future__ import annotations

import logging
import re
from typing import Type

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / Output schemas
# ---------------------------------------------------------------------------

class SQLErrorClassifierInput(BaseModel):
    """Input schema for the sql_error_classifier tool."""

    error_message: str = Field(
        default="", description="Error message from SQL execution"
    )
    error_type_hint: str = Field(
        default="",
        description="Error type hint from the sql_executor (e.g. 'syntax_error')",
    )
    all_tests_passed: bool = Field(
        default=True, description="Whether every test case passed"
    )
    failed_test_details: str = Field(
        default="",
        description="Details of failing test cases (column/row mismatches)",
    )
    student_query: str = Field(
        default="", description="The student's SQL query for context"
    )


class SQLClassificationResult(BaseModel):
    """Structured classification output."""

    error_type: str = Field(..., description="One of the SQL taxonomy categories")
    error_message: str = Field(..., description="Human-readable description")
    problematic_clause: str | None = Field(
        None,
        description="The SQL clause most likely causing the issue (SELECT, WHERE, JOIN, GROUP BY, etc.)",
    )
    severity: str = Field(default="medium", description="low / medium / high")


# ---------------------------------------------------------------------------
# Pattern rules (ordered by priority)
# ---------------------------------------------------------------------------

_SYNTAX_PATTERNS = [
    re.compile(r"syntax error", re.IGNORECASE),
    re.compile(r"unexpected end of input", re.IGNORECASE),
    re.compile(r"missing .+ at end of input", re.IGNORECASE),
]

_COLUMN_PATTERNS = [
    re.compile(r'column\s+"?\w+"?\s+does not exist', re.IGNORECASE),
    re.compile(r"unknown column", re.IGNORECASE),
]

_RELATION_PATTERNS = [
    re.compile(r'relation\s+"?[\w.]+"?\s+does not exist', re.IGNORECASE),
    re.compile(r"table .+ doesn.t exist", re.IGNORECASE),
    re.compile(r"unknown table", re.IGNORECASE),
]

_JOIN_PATTERNS = [
    re.compile(r"missing FROM-clause entry", re.IGNORECASE),
    re.compile(r"invalid reference to FROM-clause", re.IGNORECASE),
]

_AGGREGATION_PATTERNS = [
    re.compile(r"must appear in the GROUP BY clause", re.IGNORECASE),
    re.compile(r"aggregate function", re.IGNORECASE),
    re.compile(r"not allowed with GROUP BY", re.IGNORECASE),
]

_AMBIGUITY_PATTERNS = [
    re.compile(r"ambiguous", re.IGNORECASE),
]

_TYPE_PATTERNS = [
    re.compile(r"invalid input syntax for type", re.IGNORECASE),
    re.compile(r"cannot cast", re.IGNORECASE),
    re.compile(r"operator does not exist", re.IGNORECASE),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"statement timeout", re.IGNORECASE),
    re.compile(r"cancel", re.IGNORECASE),
    re.compile(r"timed?\s*out", re.IGNORECASE),
]

_SUBQUERY_PATTERNS = [
    re.compile(r"subquery must return only one column", re.IGNORECASE),
    re.compile(r"more than one row returned by a subquery", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# LangChain Tool (replaces CrewAI BaseTool)
# ---------------------------------------------------------------------------

@tool(args_schema=SQLErrorClassifierInput)
def sql_error_classifier_tool(
    error_message: str = "",
    error_type_hint: str = "",
    all_tests_passed: bool = True,
    failed_test_details: str = "",
    student_query: str = "",
) -> str:
    """Classify SQL query errors into pedagogical categories:
    syntax_error, column_error, relation_error, join_error,
    aggregation_error, subquery_error, type_error, logic_error,
    ambiguity_error, timeout_error, or no_error."""
    result = classify_sql_error(
        error_message=error_message,
        error_type_hint=error_type_hint,
        all_tests_passed=all_tests_passed,
        failed_test_details=failed_test_details,
        student_query=student_query,
    )
    return (
        f"ERROR_TYPE: {result.error_type}\n"
        f"ERROR_MESSAGE: {result.error_message}\n"
        f"PROBLEMATIC_CLAUSE: {result.problematic_clause}\n"
        f"SEVERITY: {result.severity}"
    )


# ---------------------------------------------------------------------------
# Standalone helper
# ---------------------------------------------------------------------------

def classify_sql_error(
    error_message: str = "",
    error_type_hint: str = "",
    all_tests_passed: bool = True,
    failed_test_details: str = "",
    student_query: str = "",
) -> SQLClassificationResult:
    """Classify a SQL error using pattern matching."""

    # 1. No error
    if not error_message and all_tests_passed:
        return SQLClassificationResult(
            error_type="no_error",
            error_message="All tests passed. Query is correct.",
            severity="low",
        )

    # If we have an executor error_type_hint, use it as a fast path
    if error_type_hint == "security_violation":
        return SQLClassificationResult(
            error_type="security_violation",
            error_message="Query contains a forbidden statement. Only SELECT queries are allowed.",
            severity="high",
        )

    # 2. Timeout
    for pat in _TIMEOUT_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="timeout_error",
                error_message=(
                    "Query execution timed out. This may indicate a missing index, "
                    "a Cartesian product from missing JOIN conditions, or an "
                    "overly complex subquery."
                ),
                problematic_clause=_guess_clause(student_query, "FROM"),
                severity="high",
            )

    # 3. Syntax error
    for pat in _SYNTAX_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="syntax_error",
                error_message=error_message,
                problematic_clause=_guess_problematic_clause_from_error(error_message),
                severity="medium",
            )

    # 4. Column error
    for pat in _COLUMN_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="column_error",
                error_message=error_message,
                problematic_clause="SELECT",
                severity="medium",
            )

    # 5. Relation / table error
    for pat in _RELATION_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="relation_error",
                error_message=error_message,
                problematic_clause="FROM",
                severity="medium",
            )

    # 6. Join error
    for pat in _JOIN_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="join_error",
                error_message=error_message,
                problematic_clause="JOIN",
                severity="medium",
            )

    # 7. Aggregation error
    for pat in _AGGREGATION_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="aggregation_error",
                error_message=error_message,
                problematic_clause="GROUP BY",
                severity="medium",
            )

    # 8. Ambiguity error
    for pat in _AMBIGUITY_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="ambiguity_error",
                error_message=error_message,
                problematic_clause="SELECT",
                severity="medium",
            )

    # 9. Type error
    for pat in _TYPE_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="type_error",
                error_message=error_message,
                severity="medium",
            )

    # 10. Subquery error
    for pat in _SUBQUERY_PATTERNS:
        if pat.search(error_message):
            return SQLClassificationResult(
                error_type="subquery_error",
                error_message=error_message,
                problematic_clause="subquery",
                severity="medium",
            )

    # 11. Logic error (query runs but returns wrong results)
    if not error_message and not all_tests_passed:
        problematic = _guess_logic_error_clause(failed_test_details, student_query)
        return SQLClassificationResult(
            error_type="logic_error",
            error_message=(
                "Query executes successfully but returns incorrect results. "
                "Check your filtering conditions, joins, or aggregations."
            ),
            problematic_clause=problematic,
            severity="medium",
        )

    # 12. Generic fallback
    return SQLClassificationResult(
        error_type="runtime_error",
        error_message=error_message or "Unknown SQL error.",
        severity="medium",
    )


# ---------------------------------------------------------------------------
# Clause-guessing helpers
# ---------------------------------------------------------------------------

def _guess_problematic_clause_from_error(error_msg: str) -> str | None:
    """Try to guess which SQL clause caused a syntax error."""
    lower = error_msg.lower()
    if "select" in lower:
        return "SELECT"
    if "from" in lower:
        return "FROM"
    if "where" in lower:
        return "WHERE"
    if "group" in lower:
        return "GROUP BY"
    if "order" in lower:
        return "ORDER BY"
    if "having" in lower:
        return "HAVING"
    if "join" in lower:
        return "JOIN"
    return None


def _guess_clause(query: str, default: str = "SELECT") -> str:
    """Return the last major clause found in the query."""
    clauses = ["SELECT", "FROM", "WHERE", "JOIN", "GROUP BY", "HAVING", "ORDER BY"]
    found = default
    for clause in clauses:
        if re.search(rf"\b{clause}\b", query, re.IGNORECASE):
            found = clause
    return found


def _guess_logic_error_clause(
    failed_details: str, student_query: str
) -> str | None:
    """Heuristic to guess which clause causes a logic error."""
    lower_details = failed_details.lower()

    if "column mismatch" in lower_details:
        return "SELECT"
    if "row count" in lower_details:
        if re.search(r"\bWHERE\b", student_query, re.IGNORECASE):
            return "WHERE"
        if re.search(r"\bJOIN\b", student_query, re.IGNORECASE):
            return "JOIN"
        return "FROM"
    if "row content" in lower_details:
        return "WHERE"
    return None
