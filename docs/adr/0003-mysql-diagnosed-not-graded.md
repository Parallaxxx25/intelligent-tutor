# MySQL-dialect submissions are diagnosed, never graded

> **Amended by [0006-partner-primary-dual-grade](0006-partner-primary-dual-grade.md):** the
> student-facing verdict now comes from the partner's own SQLite grader, not ours — our Postgres
> run exists only to mint a `hint_token` and diagnose. That changes the cost of a bounded,
> security-checked transpile retry from "silently changes the verdict" to "stops every
> MySQL-dialect submission from being diagnosed as a generic syntax error." `execute_sql` now
> retries once, on `syntax_error` only, through `sqlglot.transpile(read="mysql")` — re-validated
> against the same allowlist/blocklist as the original query — and marks the result
> `dialect_normalized: true` rather than pretending it was the query as typed. This *does* let a
> MySQL-dialect-but-otherwise-correct query pass our own `grading_passed`, unlike the original
> decision below — acceptable now because our Postgres verdict no longer decides what the student
> sees (0006); it mostly just stops our verdict from disagreeing with the partner's SQLite grader,
> which already accepts MySQL syntax natively. What the original decision protected —
> `interaction_history.submitted_code` is always the raw query the student typed, never the
> rewrite — is unchanged; only the *result* of execution is retried, not what gets stored or shown
> back to the student as their own query.

Students were taught MySQL syntax; this grader runs on PostgreSQL — 8 of
24 Gold Queries were themselves MySQL-dialect and had to be repaired
(`scripts/repair_golds.py`). For *student submissions*, we decided a
MySQL-valid-but-Postgres-invalid query still **fails**, with a `dialect_note`
prepended to the hint naming the mismatch (`backend/dialect.py`) — we never
transpile the submission and grade the transpiled text.

Rejected alternative: silently transpiling and grading the result (kinder
short-term, but the grader would then be evaluating text the student didn't
write, and a semantics-changing transpile — e.g. `CONCAT` → `||` differs on
NULL — could silently change the verdict). We also found and removed an
existing bug in this spirit: `_format_sql_query()` was pretty-printing every
submission through sqlglot before grading, which happened to normalize
`AS 'alias'` → `AS "alias"` and made this exact class of query pass when it
shouldn't have — removed rather than kept, since it also meant
`interaction_history.submitted_code` was storing a rewritten query instead
of what the student actually typed.
