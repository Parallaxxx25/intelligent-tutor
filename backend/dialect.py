"""
Dialect diagnosis — names a MySQL-vs-Postgres syntax mismatch in the hint
without ever grading the transpiled query.

Students in this course were taught MySQL syntax (single-quoted aliases,
backtick identifiers); the grader runs on PostgreSQL. On a syntax error we
check whether the query is valid MySQL and, if so, surface that fact so the
hint can name the dialect instead of just saying "syntax error near quote".
The submission still fails — grading only ever evaluates what the student
typed, never a transpiled rewrite of it.
"""

from __future__ import annotations

import sqlglot

DIALECT_NOTE = (
    "This looks like MySQL syntax. PostgreSQL uses double quotes for "
    'identifiers/aliases (e.g. AS "Total Price", not AS \'Total Price\'), '
    "and || instead of CONCAT() for string concatenation."
)


def diagnose_dialect(query: str) -> str | None:
    """Return a student-facing dialect note if *query* parses as MySQL,
    else None. Never used for grading.

    Caller contract: only call this after the query has already failed to
    *execute* against the real Postgres database with a syntax error —
    sqlglot's own Postgres parser is more lenient than the engine (it
    happily parses ``AS 'Total Price'``, which real Postgres rejects), so
    it can't be used here to confirm the query is invalid Postgres.
    """
    try:
        sqlglot.transpile(query, read="mysql", write="postgres")
    except Exception:
        return None  # not valid MySQL either — a genuine syntax error

    return DIALECT_NOTE
