"""
Grader Agent — Executes SQL queries and compares result sets.

Responsible for:
  - Taking student SQL query + gold-standard test queries
  - Running both via the SQLTestRunnerTool
  - Producing structured pass/fail results

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

from crewai import Agent

from backend.config import get_settings
from backend.prompts.grader_prompts import GRADER_SYSTEM_PROMPT
from backend.tools.code_executor import SQLExecutorTool
from backend.tools.test_runner import SQLTestRunnerTool

_settings = get_settings()


def create_grader_agent() -> Agent:
    """Factory function to create a configured Grader Agent."""
    return Agent(
        role="SQL Query Grader",
        goal=(
            "Execute student SQL queries against the target database and compare "
            "results with gold-standard queries. Provide accurate pass/fail "
            "results with detailed feedback on column matches, row counts, "
            "and data correctness."
        ),
        backstory=(
            "You are an expert in SQL education with 15 years of experience "
            "in automated database grading systems. You are known for your "
            "precision and objectivity — you never miss a failing query, and "
            "you never mark correct SQL as wrong. You evaluate queries exactly "
            "as submitted, without modifications."
        ),
        tools=[SQLExecutorTool(), SQLTestRunnerTool()],
        llm=_settings.LLM_MODEL,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        max_retry_limit=2,
        system_template=GRADER_SYSTEM_PROMPT,
    )
