"""
SQL Executor Tool — Runs student SQL queries against a PostgreSQL database.

Executes queries in a sandboxed read-only transaction with:
  - Configurable timeout (default 5 s)
  - Statement-level validation (blocks DDL / DML mutations)
  - Row-limit safety cap
  - Result capture as tabular data

Version: 2026-02-12  (SQL-focused rewrite)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Type

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backend.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blocked SQL patterns (security)
# ---------------------------------------------------------------------------

_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(DROP|TRUNCATE|ALTER|CREATE|INSERT|UPDATE|DELETE|GRANT|REVOKE)\b", re.IGNORECASE),
    re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE),
    re.compile(r"\bLOAD\s+DATA\b", re.IGNORECASE),
    re.compile(r"\bEXEC(UTE)?\b", re.IGNORECASE),
    re.compile(r";\s*\b(DROP|ALTER|CREATE|INSERT|UPDATE|DELETE)\b", re.IGNORECASE),
]

_ALLOWED_STATEMENTS = re.compile(
    r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE
)

MAX_RESULT_ROWS = 200


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class SQLExecutorInput(BaseModel):
    """Input schema for the sql_executor tool."""

    query: str = Field(..., description="The SQL query to execute")
    database_url: str = Field(
        default="",
        description="PostgreSQL connection URL (leave empty to use default TargetDB)",
    )


# ---------------------------------------------------------------------------
# LangChain Tool (replaces CrewAI BaseTool)
# ---------------------------------------------------------------------------

@tool(args_schema=SQLExecutorInput)
def sql_executor_tool(query: str, database_url: str = "") -> str:
    """Executes a SQL SELECT query against the tutoring target database
    in a read-only transaction with a timeout. Returns the column names
    and result rows or any error messages."""
    result = execute_sql(query, database_url or None)

    if not result["success"]:
        return (
            f"SQL_ERROR: {result['error_type']}\n"
            f"MESSAGE: {result['error_message']}\n"
        )

    # Format as a simple table
    columns = result["columns"]
    rows = result["rows"]
    header = " | ".join(columns)
    separator = "-+-".join("-" * len(c) for c in columns)
    body = "\n".join(
        " | ".join(str(v) for v in row) for row in rows
    )
    return (
        f"SUCCESS\n"
        f"ROWS_RETURNED: {len(rows)}\n"
        f"EXECUTION_TIME_MS: {result['execution_time_ms']}\n"
        f"COLUMNS: {columns}\n\n"
        f"{header}\n{separator}\n{body}"
    )


# ---------------------------------------------------------------------------
# Standalone helper (used by TestRunnerTool and tests)
# ---------------------------------------------------------------------------

def execute_sql(
    query: str,
    database_url: str | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """
    Execute a SQL query and return a structured dict.

    The query runs inside a **read-only transaction** that is always
    rolled back (no side-effects).

    Returns:
        {
            "success": bool,
            "columns": list[str],
            "rows": list[tuple],
            "row_count": int,
            "execution_time_ms": int,
            "error_type": str | None,
            "error_message": str | None,
        }
    """
    import time

    settings = get_settings()
    timeout = timeout or settings.CODE_EXEC_TIMEOUT
    db_url = database_url or settings.POSTGRES_URL_SYNC

    # --- Safety check: only SELECT / WITH / EXPLAIN -----------------------
    if not _ALLOWED_STATEMENTS.match(query.strip()):
        return _error_result(
            "security_violation",
            "Only SELECT, WITH, and EXPLAIN statements are allowed.",
        )

    for pat in _DANGEROUS_PATTERNS:
        if pat.search(query):
            return _error_result(
                "security_violation",
                f"Query contains a forbidden keyword: {pat.pattern}",
            )

    # --- Execute query ----------------------------------------------------
    try:
        import psycopg2
        from psycopg2 import sql as psql  # noqa: F401

        # Set a configurable search path so queries don't fail when querying
        # specific schemas without typing them out (e.g. production.products)
        search_path = "public,production,sales"
        conn = psycopg2.connect(
            db_url,
            options=f"-c statement_timeout={timeout * 1000} -c search_path={search_path}"
        )
        conn.set_session(readonly=True, autocommit=False)

        try:
            start = time.perf_counter()
            cur = conn.cursor()
            cur.execute(query)

            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_RESULT_ROWS) if cur.description else []
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return {
                "success": True,
                "columns": columns,
                "rows": [tuple(row) for row in rows],
                "row_count": len(rows),
                "execution_time_ms": elapsed_ms,
                "error_type": None,
                "error_message": None,
            }

        finally:
            conn.rollback()  # Always rollback — no mutations
            conn.close()

    except Exception as exc:
        error_str = str(exc).strip()
        error_type = _classify_sql_exception(error_str)
        return _error_result(error_type, error_str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_result(error_type: str, message: str) -> dict[str, Any]:
    """Build a standard error response dict."""
    return {
        "success": False,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "execution_time_ms": 0,
        "error_type": error_type,
        "error_message": message,
    }


def _classify_sql_exception(error_str: str) -> str:
    """Quick classification of a psycopg2 exception string."""
    lower = error_str.lower()

    if "syntax error" in lower:
        return "syntax_error"
    if "does not exist" in lower:
        if "column" in lower:
            return "column_error"
        if "relation" in lower or "table" in lower:
            return "relation_error"
        return "reference_error"
    if "ambiguous" in lower:
        return "ambiguity_error"
    if "permission denied" in lower:
        return "permission_error"
    if "division by zero" in lower:
        return "runtime_error"
    if "statement timeout" in lower or "cancel" in lower:
        return "timeout_error"
    if "data type" in lower or "type" in lower:
        return "type_error"
    if "group by" in lower or "aggregate" in lower:
        return "aggregation_error"
    return "runtime_error"
