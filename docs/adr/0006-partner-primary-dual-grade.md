# Partner-primary grading with a dual-grade hint contract (supersedes ADR-0001)

We integrated against the actual partner platform (`Whiterose48/Project_1_ITS-SQL`) instead of
the hypothetical one ADR-0001 was written against. Two things ADR-0001 assumed turned out to be
wrong once the real repo was read: the platform already has its own SQLite grading sandbox
(`backend/app/services/grading_service.py`) actively used in production, not a failover path
bolted on later — and it ships **81** problems from its own seed, not the 24 we could match by
CSV row.

**The verdict a student sees now comes from the partner's SQLite grader, not from us.** Our
Postgres runs alongside it on every submission (`POST /api/v1/grade`, called with the partner's
own verdict attached as `partner_verdict`), but it no longer decides pass/fail for the student.
This is the reverse of ADR-0001's "our Postgres is the sole grading authority."

Two consequences follow directly:

**We import the partner's 81-problem catalog into our own Postgres** (`Problem.external_problem_id`,
populated by `scripts/import_partner_problems.py`), rather than asking them to cut their catalog
down to our 24. The 24 CSV-sourced problems stay in the table (existing eval artifacts —
`judge_results_bike.csv`, `results_ragas_bike.csv` — still reference them) but carry no
`external_problem_id`, so the partner's catalog import never touches them.

**We still grade every submission ourselves, purely to mint a `hint_token`.** A hint is
worthless without the failed-test row and raw Postgres error `diagnose_and_hint` needs, and those
only exist if *our* grader ran. `POST /api/v1/grade` now mints `hint_token` whenever *either*
grader saw a failure (`not passed or partner_verdict != "pass"`), not just when ours did —
otherwise a submission we score correct but their SQLite scores wrong (dialect drift, mostly)
leaves the student with no way to ask for a hint at all. When the disagreement runs the other way
— we say pass, they say fail — `/api/v1/hint` returns a fixed rule-based hint pointing at
column-name/row-order mismatches instead of calling Gemini: our own diagnosis would come back
`no_error`, so an LLM call there has nothing to explain. Both directions of disagreement are
counted (`metrics.grader_disagreement_total`, keyed by `problem_id`) — live divergence data,
not just the pre-lab `gold_audit.csv` estimate.

Rejected alternative: keep ADR-0001's model and ask the partner to adopt our 24-problem catalog
and hand grading authority to us outright. Rejected because their platform already serves ~200
students against 81 problems in production — the smaller, less disruptive change is for our
service to sit alongside their existing grader as the pedagogy layer, not to replace working
infrastructure that predates this integration.

See also [0003-mysql-diagnosed-not-graded](0003-mysql-diagnosed-not-graded.md), amended
alongside this decision to allow a bounded, security-checked MySQL→Postgres retry — necessary
because the partner's 81 problems were authored for the MySQL dialect their students are taught,
and our diagnosis needs to not be "syntax error" on every dialect-only mismatch.
