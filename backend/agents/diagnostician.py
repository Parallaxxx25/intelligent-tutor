"""
Diagnostician Node — SQL error classification and hint-level recommendation.

Responsible for:
  - Analysing SQL grading results
  - Classifying errors by SQL pedagogical taxonomy
  - Identifying the problematic SQL clause
  - Determining appropriate pedagogical intervention level

Version: 2026-03-20 (LangGraph migration)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.tools.error_classifier import classify_sql_error

logger = logging.getLogger(__name__)


def diagnose_errors(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node: Diagnose SQL errors from grading results.

    Reads from state:
        - student_code: str
        - grading_raw: dict
        - attempt_count: int
        - problem_topic: str

    Returns state updates:
        - classification: SQLClassificationResult
        - diagnosis_error_type: str
        - diagnosis_error_message: str
        - diagnosis_problematic_clause: str | None
        - diagnosis_severity: str
        - recommended_hint_level: int
        - pedagogical_rationale: str
    """
    student_code = state["student_code"]
    grading_raw = state["grading_raw"]
    attempt_count = state.get("attempt_count", 1)

    # Prepare failed test details for classifier
    failed_details = json.dumps(
        [tr for tr in grading_raw["test_results"] if not tr["passed"]],
        indent=2,
        default=str,
    )

    classification = classify_sql_error(
        error_message=grading_raw.get("student_error") or "",
        error_type_hint=grading_raw.get("student_error_type") or "",
        all_tests_passed=grading_raw.get("passed", False),
        failed_test_details=failed_details,
        student_query=student_code,
    )

    # Determine hint level from attempt count
    if attempt_count <= 1:
        rec_level = 1
    elif attempt_count == 2:
        rec_level = 2
    elif attempt_count == 3:
        rec_level = 3
    else:
        rec_level = 4

    rationale = (
        f"Rule-based diagnosis. Attempt {attempt_count}. "
        f"Error type is {classification.error_type} "
        f"(clause: {classification.problematic_clause}) with "
        f"{classification.severity} severity."
    )

    logger.info(
        "Diagnostician node: %s (clause=%s, level=%d)",
        classification.error_type,
        classification.problematic_clause,
        rec_level,
    )

    return {
        "classification": classification,
        "diagnosis_error_type": classification.error_type,
        "diagnosis_error_message": classification.error_message,
        "diagnosis_problematic_clause": classification.problematic_clause,
        "diagnosis_severity": classification.severity,
        "recommended_hint_level": rec_level,
        "pedagogical_rationale": rationale,
    }
