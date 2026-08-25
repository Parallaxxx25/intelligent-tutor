# Domain Glossary

Terms for the SQL tutoring system, sharpened during the lab-release planning
pass (see `docs/adr/` for the decisions these terms sit inside).

## Problem

One of the **24** seeded exercises (12 Practice + 12 Assignment, from
`sql-problem/Practice-Assignment-Bike shop-2025.csv`). A Problem's `id` in
this system's Postgres is the identifier shared with any integrating
platform — an integrator imports these 24 and stores this id as its own
foreign key (`tutor_problem_id`), rather than maintaining separate problem
text that could drift from the Gold Query it's graded against.

## Gold Query

The single reference SQL query a submission is graded against. Stored
today in two places that hold the *same string* — `test_cases.input_data`
(what the grader executes) and `gold_standards.solution_code` (documented
as "never shown to students," currently unused for that purpose). Not to
be confused with the **Hint Solution Template** (Hint Level 4), which is a
deliberately incomplete scaffold, not the Gold Query itself.

## Verdict

The outcome of grading a submission against a Problem's Gold Query: **pass**,
**fail**, or **ungradable** (the Gold Query itself exceeds the row bound, or
overflows it — never silently compared as if it were smaller than it is).
Today's catalog has exactly one test case per Problem, so `score` is always
either `0.0` or `1.0` — there is no partial credit.

## Label Mismatch

A submission whose column *values* match the Gold Query but whose column
*names* don't (e.g. Gold Query aliases `AS full_name`, submission has no
alias). Does **not** affect the Verdict — see
[0002-column-labels-do-not-affect-verdict](docs/adr/0002-column-labels-do-not-affect-verdict.md).
Surfaced to the Diagnostician as a flag, not a failure.

## Dialect Note

A hint prefix naming a MySQL-vs-PostgreSQL syntax mismatch (e.g. `AS 'alias'`
vs `AS "alias"`). Attached only when the submission already failed to
*execute* against the real database with a `syntax_error` — never used to
decide the Verdict. See
[0003-mysql-diagnosed-not-graded](docs/adr/0003-mysql-diagnosed-not-graded.md).

## Attempt / Hint Level

**Attempt** — the count of a student's submissions to one Problem, tracked
in `student_progress.attempts` (Postgres, authoritative) and mirrored
best-effort in the student's Redis session. **Hint Level** — the 1–4
pedagogical scaffold tier (1 Attention → 4 Solution Template), chosen by
the Escalation Policy. Superseded: this used to be a pure function of the
Attempt count (attempt 1→L1, 2→L2, 3→L3, 4+→L4); that rule now survives
only as the Escalation Policy's fallback when no richer signal is
available — see
[0005-multi-signal-hint-escalation](docs/adr/0005-multi-signal-hint-escalation.md).

## Escalation Policy

The pure, deterministic function (`backend/agents/escalation_policy.py::
decide_hint_level`) that turns this attempt's signals — attempt count,
error-type stability across recent attempts, whether the resubmitted query
changed, dwell time since the last submission, and topic mastery on
sibling Problems sharing the same `Problem.topic` — into an **Escalation
Decision**: the Hint Level plus a list of **Drivers** (short machine-
readable tags like `error_type_stable_2x` or `query_unchanged_fast_hold`)
explaining why. The Escalation Policy is authoritative over Gemini's own
proposed level in the LLM pipeline; Gemini's proposal is recorded
alongside the decision, never used to raise or lower it. Never itself
calls an LLM — reproducible and independently unit-testable by design.

## Diagnosis

The classification of *why* a failed submission failed, into the
`ErrorType` taxonomy (syntax/column/relation/join/aggregation/subquery/
type/ambiguity/logic/runtime/timeout/security_violation/no_error). Produced
by the rule-based classifier always; optionally refined by Gemini in the LLM
pipeline, with the rule-based result as fallback context.

## Hint Fallback vs. Grading Failover

Two different things that have both been called "fallback" — keep them
separate:

- **Hint Fallback** — within *our* service, when the LLM hint path fails
  (timeout, guardrail rejection, Gemini error) and the rule-based hint
  generator answers instead. Tracked per-hint via `HintResponse.source`
  (`"llm"` | `"rule_based"`) and `fallback_reason`.
- **Grading Failover** — when an *integrating platform* can't reach our
  `/grade` at all (we're down or timing out) and falls back to its own
  local grader. Tagged on the stored interaction as `verdict_source`
  (`"primary"` | `"client_failover"`) so those rows can be excluded from
  analysis — two graders can disagree.

## Submission Token / Hint Token

The opaque handle returned by grading that a subsequent hint request must
present to retrieve the hint for that specific submission — stored as
`interaction_history.hint_token`, never trusted from client-supplied
grading data. See
[0004-hint-artifact-in-postgres-not-redis](docs/adr/0004-hint-artifact-in-postgres-not-redis.md).

## External Student Id

An opaque identifier for a student, supplied by an integrating platform —
never an email or other directly-identifying value. This system
auto-provisions a `users` row keyed on it the first time it's seen.
