# MySQL-dialect submissions are diagnosed, never graded

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
