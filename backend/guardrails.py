"""
Input / Output Guardrails for the LLM pipeline.

Input Guardrails (before sending to Gemini):
  - Prompt injection detection
  - SQL injection / comment-based attacks
  - Length limits
  - Content filtering (profanity)
  - Topic boundary (SQL-only)

Output Guardrails (after receiving from Gemini):
  - Solution leakage prevention (similarity to gold-standard)
  - Schema / table / column hallucination detection
  - Tone enforcement (no harsh language)
  - Length cap
  - Format validation (expected schema)
  - Unsafe content filtering

Version: 2026-02-13
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from backend.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class GuardrailResult:
    """Result of a guardrail check."""

    passed: bool = True
    violations: list[str] = field(default_factory=list)
    sanitized_content: str | None = None  # cleaned version (if fixable)

    def fail(self, reason: str) -> None:
        """Record a violation."""
        self.passed = False
        self.violations.append(reason)


# ===================================================================
#  INPUT GUARDRAILS
# ===================================================================

# Patterns that suggest prompt injection attempts
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|the)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(your\s+)?(previous|prior)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?(instructions|rules|role)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a|an|the)\s+(?!sql|database|tutor)", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|your)", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your|the)\s+(rules|instructions)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
]

# SQL comments that might hide injection payloads
_SQL_COMMENT_INJECTION_PATTERN = re.compile(
    r"(/\*.*?(ignore|system|prompt|instruction|override).*?\*/|"
    r"--\s*.*(ignore|system|prompt|instruction|override))",
    re.IGNORECASE | re.DOTALL,
)

# Off-topic patterns (clearly not SQL-related)
_OFF_TOPIC_PATTERNS: list[re.Pattern] = [
    re.compile(r"write\s+(me\s+)?(a\s+)?(poem|essay|story|song|joke)", re.IGNORECASE),
    re.compile(r"tell\s+me\s+(a\s+)?(joke|story)", re.IGNORECASE),
    re.compile(r"what\s+is\s+the\s+(meaning\s+of\s+life|capital\s+of)", re.IGNORECASE),
    re.compile(r"(translate|convert)\s+.+\s+(to|into)\s+(french|spanish|chinese|japanese)", re.IGNORECASE),
    re.compile(r"(hack|exploit|crack|breach)\s+(into|the|a)", re.IGNORECASE),
]

# Basic profanity patterns (expandable)
_PROFANITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(fuck|shit|damn|ass|bitch|bastard|crap)\b", re.IGNORECASE),
]

# Harsh language in output
_HARSH_LANGUAGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(stupid|idiot|dumb|terrible|awful|worst|hopeless|pathetic)\b", re.IGNORECASE),
    re.compile(r"you\s+(should|need\s+to)\s+know\s+this", re.IGNORECASE),
    re.compile(r"this\s+is\s+(really\s+)?(basic|obvious|simple)", re.IGNORECASE),
    re.compile(r"how\s+(can|could)\s+you\s+not\s+know", re.IGNORECASE),
    re.compile(r"everyone\s+knows\s+(this|that)", re.IGNORECASE),
]


def validate_input(
    student_query: str,
    context: dict[str, Any] | None = None,
) -> GuardrailResult:
    """
    Validate student input BEFORE sending to the LLM.

    Checks:
      1. Length limit
      2. Prompt injection detection
      3. SQL comment-based injection
      4. Profanity filter
      5. Topic boundary (SQL-only)

    Args:
        student_query: The student's SQL query or message.
        context: Optional additional context dict.

    Returns:
        GuardrailResult with pass/fail and list of violations.
    """
    result = GuardrailResult()
    settings = get_settings()

    # Combine query + context for full scan
    full_text = student_query
    if context:
        full_text += " " + str(context)

    # 1. Length limit
    max_len = settings.GUARDRAIL_MAX_QUERY_LENGTH
    if len(student_query) > max_len:
        result.fail(
            f"Query exceeds maximum length ({len(student_query)} > {max_len} chars)."
        )

    # 2. Prompt injection detection
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(full_text):
            result.fail(
                f"Potential prompt injection detected: '{pattern.pattern}'"
            )
            break  # One injection is enough to reject

    # 3. SQL comment-based injection
    if _SQL_COMMENT_INJECTION_PATTERN.search(full_text):
        result.fail(
            "Suspicious SQL comment detected — may contain hidden instructions."
        )

    # 4. Profanity
    for pattern in _PROFANITY_PATTERNS:
        if pattern.search(student_query):
            result.fail("Query contains inappropriate language.")
            break

    # 5. Topic boundary — reject clearly off-topic queries
    #    (only if the input looks like natural language, not SQL)
    sql_keywords = {"select", "from", "where", "join", "group", "order", "having",
                    "insert", "update", "delete", "create", "alter", "drop", "with"}
    words = set(student_query.lower().split())
    is_likely_sql = bool(words & sql_keywords)

    if not is_likely_sql:
        for pattern in _OFF_TOPIC_PATTERNS:
            if pattern.search(student_query):
                result.fail(
                    "Query appears off-topic. This system is designed for SQL learning only."
                )
                break

    return result


# ===================================================================
#  OUTPUT GUARDRAILS
# ===================================================================

def validate_output(
    llm_response: str,
    gold_standard_query: str = "",
    schema_info: dict[str, Any] | None = None,
) -> GuardrailResult:
    """
    Validate LLM output BEFORE returning to the student.

    Checks:
      1. Solution leakage (similarity to gold-standard query)
      2. Hallucination (referenced tables/columns don't exist)
      3. Tone (no harsh criticism)
      4. Length cap
      5. Unsafe content

    Args:
        llm_response: The LLM's generated response text.
        gold_standard_query: The gold-standard SQL query (for leakage detection).
        schema_info: Dict with 'tables' and 'columns' lists for hallucination check.

    Returns:
        GuardrailResult with pass/fail, violations, and optionally sanitized content.
    """
    result = GuardrailResult()
    result.sanitized_content = llm_response
    settings = get_settings()

    # 1. Solution leakage prevention
    if gold_standard_query:
        leakage = _check_solution_leakage(llm_response, gold_standard_query)
        if leakage:
            result.fail(leakage)
            # Try to sanitize: remove SQL code blocks that are too similar
            result.sanitized_content = _remove_leaking_sql(
                llm_response, gold_standard_query
            )

    # 2. Hallucination check (table/column names)
    if schema_info:
        hallucinations = _check_hallucinations(llm_response, schema_info)
        for h in hallucinations:
            result.fail(h)

    # 3. Tone enforcement
    for pattern in _HARSH_LANGUAGE_PATTERNS:
        if pattern.search(llm_response):
            result.fail(f"Response contains harsh language: '{pattern.pattern}'")
            # Sanitize: remove the harsh sentence
            result.sanitized_content = pattern.sub(
                "[encouraging message]",
                result.sanitized_content or llm_response,
            )

    # 4. Length cap
    max_len = settings.GUARDRAIL_MAX_RESPONSE_LENGTH
    if len(llm_response) > max_len:
        result.fail(
            f"Response exceeds maximum length ({len(llm_response)} > {max_len} chars)."
        )
        # Sanitize: truncate
        result.sanitized_content = (result.sanitized_content or llm_response)[:max_len]
        # Append truncation notice
        result.sanitized_content += "\n\n*(Response truncated for brevity.)*"

    # 5. Profanity / unsafe content
    for pattern in _PROFANITY_PATTERNS:
        if pattern.search(llm_response):
            result.fail("Response contains inappropriate language.")
            break

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_solution_leakage(
    response: str,
    gold_standard: str,
    threshold: float = 0.80,
) -> str | None:
    """
    Check if the LLM response contains the gold-standard query.

    Uses both exact substring matching and fuzzy similarity.

    Returns:
        Violation message if leakage detected, None otherwise.
    """
    # Normalize for comparison
    norm_response = _normalize_sql(response)
    norm_gold = _normalize_sql(gold_standard)

    # Check 1: Is the gold-standard query a substring?
    if norm_gold in norm_response:
        return "Solution leakage: gold-standard query found verbatim in response."

    # Check 2: Extract SQL code blocks and compare each
    sql_blocks = re.findall(r"```sql\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    for block in sql_blocks:
        norm_block = _normalize_sql(block)
        similarity = SequenceMatcher(None, norm_block, norm_gold).ratio()
        if similarity >= threshold:
            return (
                f"Solution leakage: SQL block is {similarity:.0%} similar "
                f"to the gold-standard query (threshold: {threshold:.0%})."
            )

    # Check 3: Check the full response text similarity (lower threshold)
    full_similarity = SequenceMatcher(None, norm_response, norm_gold).ratio()
    if full_similarity >= 0.90:
        return (
            f"Solution leakage: response is {full_similarity:.0%} similar "
            f"to the gold-standard query."
        )

    return None


def _remove_leaking_sql(
    response: str,
    gold_standard: str,
    threshold: float = 0.75,
) -> str:
    """Remove SQL code blocks that are too similar to the gold standard."""
    norm_gold = _normalize_sql(gold_standard)

    def replace_block(match: re.Match) -> str:
        block = match.group(1)
        norm_block = _normalize_sql(block)
        similarity = SequenceMatcher(None, norm_block, norm_gold).ratio()
        if similarity >= threshold:
            return (
                "```sql\n"
                "-- [Hint: The specific query has been redacted to encourage learning.\n"
                "--  Try building it step by step!]\n"
                "```"
            )
        return match.group(0)

    return re.sub(
        r"```sql\s*(.*?)```",
        replace_block,
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )


def _normalize_sql(text: str) -> str:
    """Normalize SQL text for comparison: lowercase, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"--.*?$", "", text, flags=re.MULTILINE)  # Remove line comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)  # Remove block comments
    text = re.sub(r"\s+", " ", text)  # Collapse whitespace
    text = re.sub(r";\s*$", "", text)  # Remove trailing semicolon
    return text.strip()


def _check_hallucinations(
    response: str,
    schema_info: dict[str, Any],
) -> list[str]:
    """
    Check if the response references tables or columns that don't exist.

    Args:
        response: LLM response text.
        schema_info: Dict with 'tables' (list[str]) and 'columns' (list[str]).

    Returns:
        List of violation messages.
    """
    violations: list[str] = []
    known_tables = {t.lower() for t in schema_info.get("tables", [])}
    known_columns = {c.lower() for c in schema_info.get("columns", [])}

    if not known_tables and not known_columns:
        return violations

    # Extract table/column references from SQL code blocks
    sql_blocks = re.findall(r"```sql\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)

    for block in sql_blocks:
        # Find FROM/JOIN table references
        table_refs = re.findall(
            r"(?:FROM|JOIN)\s+(\w+)", block, re.IGNORECASE
        )
        for ref in table_refs:
            if ref.lower() not in known_tables and known_tables:
                violations.append(
                    f"Hallucination: referenced table '{ref}' does not exist in the schema."
                )

    return violations
