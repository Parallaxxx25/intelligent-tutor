"""
SQL Test Runner Tool — Compares student query results to expected results.

Takes a student SQL query and a set of test cases (each with an expected
query / expected result set) and checks whether the student's output
matches.  Comparison strategies:
  - Ordered: exact row-by-row match
  - Unordered (set): same rows regardless of ordering
  - Column-only: check that the correct columns are selected

Version: 2026-02-12  (SQL-focused rewrite)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Type

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backend.tools.code_executor import execute_sql

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class SQLTestRunnerInput(BaseModel):
    """Input schema for the sql_test_runner tool."""

    student_query: str = Field(..., description="The student's submitted SQL query")
    test_cases: str = Field(
        ...,
        description=(
            "JSON array of test cases.  Each object must have: "
            "'test_case_id' (int), "
            "'expected_query' (str — the gold-standard SQL that produces the correct result), "
            "'check_order' (bool — whether row order matters)"
        ),
    )


# ---------------------------------------------------------------------------
# LangChain Tool (replaces CrewAI BaseTool)
# ---------------------------------------------------------------------------

@tool(args_schema=SQLTestRunnerInput)
def sql_test_runner_tool(student_query: str, test_cases: str) -> str:
    """Executes the student's SQL query and compares its result set
    against the expected result produced by a gold-standard query.
    Returns per-test pass/fail and an overall score."""
    try:
        cases = json.loads(test_cases)
    except json.JSONDecodeError as exc:
        return f"ERROR: Could not parse test_cases JSON — {exc}"

    results = run_sql_tests(student_query, cases)
    return json.dumps(results, indent=2, default=str)


# ---------------------------------------------------------------------------
# Standalone helper
# ---------------------------------------------------------------------------

def run_sql_tests(
    student_query: str,
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run *student_query* and compare against each test case's expected query.

    Each test case dict must have:
      - test_case_id : int
      - expected_query : str   (gold-standard SQL)
      - check_order : bool     (whether row order matters)

    Returns:
        {
            "passed": bool,
            "score": float,          # 0.0–1.0
            "total_tests": int,
            "passed_tests": int,
            "test_results": [ … ],
            "student_error": str | None,
        }
    """
    # ---- Execute student query once ------------------------------------
    student_result = execute_sql(student_query)

    if not student_result["success"]:
        # All tests fail if the student query errors
        return {
            "passed": False,
            "score": 0.0,
            "total_tests": len(test_cases),
            "passed_tests": 0,
            "test_results": [
                {
                    "test_case_id": tc.get("test_case_id", idx),
                    "passed": False,
                    "error_message": student_result["error_message"],
                    "error_type": student_result["error_type"],
                    "expected_columns": None,
                    "actual_columns": None,
                    "expected_row_count": None,
                    "actual_row_count": 0,
                }
                for idx, tc in enumerate(test_cases)
            ],
            "student_error": student_result["error_message"],
            "student_error_type": student_result["error_type"],
        }

    # ---- Compare against each test case --------------------------------
    test_results: list[dict[str, Any]] = []
    passed_count = 0

    for tc in test_cases:
        tc_id = tc.get("test_case_id", 0)
        expected_query = tc["expected_query"]
        check_order = tc.get("check_order", False)

        # Run the gold-standard query
        expected_result = execute_sql(expected_query)

        if not expected_result["success"]:
            logger.error(
                "Gold-standard query failed for test_case %d: %s",
                tc_id,
                expected_result["error_message"],
            )
            test_results.append(
                {
                    "test_case_id": tc_id,
                    "passed": False,
                    "error_message": f"Gold query error: {expected_result['error_message']}",
                    "expected_columns": None,
                    "actual_columns": student_result["columns"],
                    "expected_row_count": None,
                    "actual_row_count": student_result["row_count"],
                }
            )
            continue

        # Compare columns
        columns_match = _compare_columns(
            student_result["columns"], expected_result["columns"]
        )

        # Compare rows
        rows_match = _compare_rows(
            student_result["rows"],
            expected_result["rows"],
            ordered=check_order,
        )

        is_pass = columns_match and rows_match
        if is_pass:
            passed_count += 1

        mismatch_details = None
        if not is_pass:
            mismatch_details = _build_mismatch_details(
                student_result, expected_result, columns_match, rows_match
            )

        test_results.append(
            {
                "test_case_id": tc_id,
                "passed": is_pass,
                "error_message": mismatch_details,
                "expected_columns": expected_result["columns"],
                "actual_columns": student_result["columns"],
                "expected_row_count": expected_result["row_count"],
                "actual_row_count": student_result["row_count"],
            }
        )

    total = max(len(test_cases), 1)
    score = round(passed_count / total, 4)

    return {
        "passed": passed_count == len(test_cases),
        "score": score,
        "total_tests": len(test_cases),
        "passed_tests": passed_count,
        "test_results": test_results,
        "student_error": None,
        "student_error_type": None,
    }


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _compare_columns(actual: list[str], expected: list[str]) -> bool:
    """Check that column names match (case-insensitive)."""
    return [c.lower() for c in actual] == [c.lower() for c in expected]


def _compare_rows(
    actual: list[tuple],
    expected: list[tuple],
    ordered: bool = False,
) -> bool:
    """Compare row sets, optionally ignoring order."""
    if len(actual) != len(expected):
        return False

    if ordered:
        return actual == expected

    # Unordered comparison — sort both lists for set-like compare
    try:
        return sorted(actual) == sorted(expected)
    except TypeError:
        # Fallback for unsortable types — convert to string repr
        return sorted(str(r) for r in actual) == sorted(str(r) for r in expected)


def _build_mismatch_details(
    student: dict[str, Any],
    expected: dict[str, Any],
    columns_match: bool,
    rows_match: bool,
) -> str:
    """Build a human-readable mismatch description."""
    parts: list[str] = []

    if not columns_match:
        parts.append(
            f"Column mismatch — expected {expected['columns']}, "
            f"got {student['columns']}"
        )

    if not rows_match:
        if student["row_count"] != expected["row_count"]:
            parts.append(
                f"Row count mismatch — expected {expected['row_count']} rows, "
                f"got {student['row_count']} rows"
            )
        else:
            parts.append("Row content mismatch — same number of rows but different values")

        # Show first few differing rows
        for i, (s_row, e_row) in enumerate(
            zip(student["rows"][:3], expected["rows"][:3])
        ):
            if s_row != e_row:
                parts.append(f"  Row {i + 1}: expected {e_row}, got {s_row}")

    return "; ".join(parts)
