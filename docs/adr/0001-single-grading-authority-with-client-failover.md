# Single grading authority, 24-problem catalog, client-side failover

> **Superseded by [0006-partner-primary-dual-grade](0006-partner-primary-dual-grade.md).** Written
> against a hypothetical integration; once we integrated against the real partner platform, its
> SQLite grader turned out to already be primary in production (not a failover path) and its
> catalog is 81 problems, not 24. Kept here for the record — see 0006 for what actually shipped.

This system is one of two graders for an integrating platform (which ships
its own SQLite-based execution). We decided **this system's Postgres is the
sole grading authority** — the integrator's SQLite never grades a
submission under normal operation. This meant cutting the catalog from the
integrator's 81 problems to the **24** actually seeded here (`seed.py`
reads 12 practice + 12 assignment rows from the CSV; there is no larger
verified set to fall back to), rather than the alternative of splitting
authority by problem or having each platform grade its own subset.

Consequence accepted deliberately: if this service is down or times out,
the integrator's platform fails over to its own SQLite grader
(`verdict_source: "client_failover"`) so the lab doesn't stop — but the two
graders can disagree, so failover rows are excluded from analysis rather
than trusted as equivalent to a primary-graded verdict.
