"""
Diagnostician Agent — SQL error classification and hint-level recommendation.

Responsible for:
  - Analysing SQL grading results
  - Classifying errors by SQL pedagogical taxonomy
  - Identifying the problematic SQL clause
  - Determining appropriate pedagogical intervention level

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

from crewai import Agent

from backend.config import get_settings
from backend.prompts.diagnostician_prompts import DIAGNOSTICIAN_SYSTEM_PROMPT
from backend.tools.error_classifier import SQLErrorClassifierTool

_settings = get_settings()


def create_diagnostician_agent() -> Agent:
    """Factory function to create a configured Diagnostician Agent."""
    return Agent(
        role="SQL Error Diagnostician",
        goal=(
            "Classify SQL query errors into a pedagogical taxonomy and "
            "determine the appropriate hint level based on error type, "
            "the problematic SQL clause, and student attempt history."
        ),
        backstory=(
            "You are a specialist in SQL education with deep knowledge "
            "of common mistakes students make when learning SQL. You've spent "
            "a decade studying how students misuse JOINs, forget GROUP BY rules, "
            "and mix up WHERE vs HAVING. You can quickly identify not just WHAT "
            "went wrong but WHY a student might have written that particular query. "
            "You believe in scaffolded learning — giving just enough help at "
            "the right time."
        ),
        tools=[SQLErrorClassifierTool()],
        llm=_settings.LLM_MODEL,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        max_retry_limit=2,
        system_template=DIAGNOSTICIAN_SYSTEM_PROMPT,
    )
