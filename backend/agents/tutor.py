"""
Tutor Agent — Generates scaffolded pedagogical hints for SQL learning.

Responsible for:
  - Receiving a diagnosis (SQL error type + recommended hint level)
  - Generating an appropriate SQL-specific hint
  - Ensuring hints are encouraging and pedagogically sound

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

from crewai import Agent

from backend.config import get_settings
from backend.prompts.tutor_prompts import TUTOR_SYSTEM_PROMPT
from backend.tools.hint_generator import SQLHintGeneratorTool

_settings = get_settings()


def create_tutor_agent() -> Agent:
    """Factory function to create a configured Tutor Agent."""
    return Agent(
        role="SQL Pedagogical Tutor",
        goal=(
            "Generate scaffolded SQL hints that guide students toward "
            "understanding their mistakes without revealing the complete "
            "SQL query. Use encouraging language and promote self-reflection "
            "about SQL concepts."
        ),
        backstory=(
            "You are an experienced database instructor with a passion "
            "for constructivist learning. You've taught SQL to hundreds "
            "of students and know that the best learning happens when students "
            "figure out JOINs, GROUP BY, and subqueries themselves — with just "
            "the right amount of guidance. You're warm, patient, and always "
            "find something positive to say about the student's effort."
        ),
        tools=[SQLHintGeneratorTool()],
        llm=_settings.LLM_MODEL,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        max_retry_limit=2,
        system_template=TUTOR_SYSTEM_PROMPT,
    )
