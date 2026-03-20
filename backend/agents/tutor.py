"""
Tutor Node — Generates scaffolded pedagogical hints for SQL learning.

Responsible for:
  - Receiving a diagnosis (SQL error type + recommended hint level)
  - Generating an appropriate SQL-specific hint
  - Ensuring hints are encouraging and pedagogically sound

Version: 2026-03-20 (LangGraph migration)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.tools.hint_generator import generate_sql_hint

logger = logging.getLogger(__name__)


def generate_hint(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node: Generate a pedagogical SQL hint.

    Reads from state:
        - student_code: str
        - diagnosis_error_type: str
        - diagnosis_error_message: str
        - diagnosis_problematic_clause: str | None
        - recommended_hint_level: int
        - attempt_count: int
        - problem_description: str

    Returns state updates:
        - hint_raw: dict  (full hint payload)
        - hint_text: str
    """
    hint_raw = generate_sql_hint(
        error_type=state["diagnosis_error_type"],
        error_message=state["diagnosis_error_message"],
        student_query=state["student_code"],
        attempt_count=state.get("attempt_count", 1),
        problem_description=state.get("problem_description", ""),
        problematic_clause=state.get("diagnosis_problematic_clause"),
    )

    logger.info(
        "Tutor node: generated level-%d hint (%s)",
        hint_raw["hint_level"],
        hint_raw["hint_type"],
    )

    return {
        "hint_raw": hint_raw,
        "hint_text": hint_raw["hint_text"],
    }
