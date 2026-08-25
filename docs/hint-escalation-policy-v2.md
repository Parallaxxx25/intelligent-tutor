# Methodology: Adaptive Hint-Level Escalation Policy (v2)

## 1. Problem statement

Prior to this change, hint level was `f(attempt_count)` only: attempt 1 → Level 1, attempt 2 →
Level 2, attempt 3 → Level 3, attempt 4+ → Level 4, identically across all three pipelines
(deterministic, LangGraph, LLM). This is a fixed schedule, not an adaptive one: it cannot
distinguish a student one typo away from correct from a student with no model of JOINs at all,
and it has no mechanism to reduce support as competence is demonstrated.

## 2. Constraint → mechanism mapping

| # | Source | Constraint | Mechanism in `decide_hint_level` |
|---|---|---|---|
| 1 | Vygotsky (1978), ZPD | Support tracks current difficulty, not a global counter | The floor is still attempt-based (repetition is real evidence), but every other step conditions on *this attempt's* error type, query diff, and dwell time — not a schedule fixed in advance. |
| 2 | Wood, Bruner & Ross (1976) | Support is progressively withdrawn as competence increases; must support de-escalation, not just monotonic increase | Step 1 (mastery grace): `MASTERY_GRACE_ATTEMPTS` shifts the whole ladder right for a student ADVANCED/EXPERT on this problem's topic, read once per problem boundary. A stuck student still reaches L4 — one attempt later than an unmastered peer — so support is *reduced*, never *withheld*. |
| 3 | Sweller (1988), CLT | Don't escalate on noise; a shallow error (typo) isn't evidence of deep confusion | Step 2 (depth bump) only fires for `conceptual` or `blocking` error types (`ERROR_DEPTH` map). `shallow` types (syntax/column/relation/ambiguity/type/runtime) never bump the level regardless of repetition. |
| 4 | VanLehn (2011); Ma et al. (2014); Steenbergen-Hu & Cooper (2014) | Rigid step logic is part of why step-based tutors underperform human tutors | Motivates investing in a multi-signal policy at all; not a mechanism itself — the whole module is the response to this row. |
| 5 | Fan et al. (2024), metacognitive laziness | Don't escalate merely because the student resubmits fast; fast + unchanged resubmission is evidence the hint wasn't read, not that a stronger one is needed | Step 3 (hold): near-identical resubmission (`QUERY_SIMILARITY_THRESHOLD`) within `DWELL_MIN_SECONDS` of the previous attempt holds the level at its last-shown value instead of escalating. An unchanged query after a *long* gap is treated as genuine stuckness and allowed through. Step 4 (unprompted clamp): an empty/starter-code submission is a direct behavioral proxy for offloading — it is always logged as a driver, and clamped to Level 1 (not granted a high level) when there's no prior genuine attempt on the problem. |
| 6 | Holstein, McLaren & Aleven (2019) | AI decisions must be interpretable and overridable by a human | Every call returns an `EscalationDecision` with `drivers: tuple[str, ...]`, `signals_summary`, and `policy_version` — not just an integer. This rides in `DiagnosisResult.escalation_trace`, persisted in `interaction_history.diagnosis_details`, the intended input to a future teacher-dashboard override. |

**Non-negotiable (No Solution Leakage):** the policy changes level *selection* only.
`LEVEL_DESCRIPTIONS`, `_build_hint_prompt`, and the four `_level_N_*` rule-based generators in
`hint_generator.py` are untouched. A regression test (Phase 4) asserts the leakage guardrail
score is unchanged from v1 for every level.

## 3. Corrections to the original task specification

The original task brief (Sections 3 and 5 of the implementing prompt) assumed infrastructure
that either doesn't exist or contradicts a standing decision. These were audited against the
code before design, not discovered during implementation:

| Spec claim | Reality | Consequence |
|---|---|---|
| `backend/memory/long_term.py` (ChromaDB episodic store) exists | Removed. `interaction_history` is the sole record; Chroma is RAG-only (curated SQL knowledge, not per-student history). | No dependency on it. |
| Hint Level Compliance (56.7%) measures conformance to the attempt-count rule | It scores hint *text* against a level's *content contract* (code block present for L3, `___` blanks for L4, etc.) — `score_hint_level_compliance()` in `ragas_evaluator.py`. Orthogonal to which policy chose the level. | Only the *source* of `expected_level` in the eval dataset changes; the scorer itself is untouched (§8 non-goal). |
| Supervisor's LLM-path fallback "re-derives the same rule, confirm empirically whether it diverges" | It structurally cannot diverge upward: `min(llm_level, attempt_level)` in the pre-v2 code is one-directional by construction. | No logging/comparison exercise was needed; this is provable from the code, not an empirical question. |
| `severity` is "the cheapest available signal, currently dead data" | The rule-based classifier (`error_classifier.py`) returns `"medium"` for 9 of its 11 branches — it is *near-constant*, not a rich unused signal, in the deterministic and LangGraph pipelines. Only Gemini's severity (LLM pipeline) varies, which would make escalation arithmetic depend on an LLM — directly violating the task's own §4.6. | Replaced with a deterministic `ERROR_DEPTH` map keyed on the *existing* 11-category `ErrorType` taxonomy (§8 leaves the taxonomy untouched) rather than on `severity`. |
| Topic-level mastery groups like "JOINs" | `Problem.topic` holds 9 distinct free-text, multi-line, mixed Thai/English strings sourced verbatim from the CSV column `Topic Evaluated` (e.g. `"SELECT 2 column, column alias\nFROM 1 table"`), 1–4 problems per group, all single-table SELECT variants — there is no JOIN topic in the current 24-problem catalog. | Topic-mastery de-escalation is real but small-sample (documented honestly below, §5) rather than the multi-problem-per-topic scenario the spec implicitly assumed. |
| "Should set the starting level for a new problem... higher than Level 1" (§3) vs. `base = max(1, base - 1)` (§6 skeleton) | These contradict each other, and the skeleton's own arithmetic is a no-op on a new problem: attempt 1 → base 1 → `max(1, 1-1)` = 1. Level 4 is *more* scaffolding; per Wood et al., higher mastery should reduce support, i.e. push toward Level 1, matching the skeleton's *direction* but not its (broken) arithmetic. | Re-implemented as a grace-attempt shift on the floor (§4 below) rather than a post-hoc subtraction, so it actually changes behavior instead of canceling itself. |
| "Unprompted hint request (asked before submitting any query)" | Unrepresentable in either API surface: `/api/submit` always grades a submitted query, and `/api/v1/hint` requires a `hint_token` minted only after a failed `/api/v1/grade`. The Streamlit "Give Hint" button also POSTs to `/submit` with the textarea contents. | Operationalized instead as an empty-or-starter-code *submission* — behaviorally the same signal (effort was not invested before a hint was produced), representable with zero API changes. |
| Redis session (`SessionManager`) should hold `error_type_history`, `query_history`, `hint_level_history`, `last_hint_shown_at`, `hint_requested_unprompted` | Directly contradicts [ADR-0004](adr/0004-hint-artifact-in-postgres-not-redis.md): *"student_progress.attempts in Postgres is authoritative for hint-level escalation, so a Redis loss can't reset a student back to a level-1 hint."* `interaction_history` already stores every one of these fields (as `submitted_code`, `error_type`, `hint_level`, `timestamp`) per attempt, durably, ordered, on both API surfaces. | All new state is read from `interaction_history`, not Redis. See [ADR-0005](adr/0005-multi-signal-hint-escalation.md). |

## 4. Signals and their source

| Signal | Source | Query / field |
|---|---|---|
| `attempt_count` | `StudentProgress.attempts` (+1), as today | existing `routes.py` logic |
| `error_type` (this attempt) | Rule-based classifier output, as today | `classify_sql_error(...)` |
| `error_type_history` | Last N `interaction_history.error_type` for `(user_id, problem_id)`, oldest-first | new `_attempt_history()` |
| `query_history` | Last N `interaction_history.submitted_code` for `(user_id, problem_id)` | new `_attempt_history()` |
| `hint_level_history` | Last N `interaction_history.hint_level` for `(user_id, problem_id)` | new `_attempt_history()` |
| `seconds_since_prev` | `(now - interaction_history.timestamp)` of the most recent row | new `_attempt_history()` |
| `topic_mastery` | `MAX(StudentProgress.mastery_level)` joined to `Problem.topic`, excluding current problem | new `_topic_mastery()` |
| `current_query` | The submission being graded right now | request body |
| `starter_code` | `Problem.starter_code` | already loaded per-request |

No new columns, no new Redis fields, no Alembic migration (the codebase has none —
`database.py` uses `create_all`, which cannot alter existing tables).

## 5. Constants (Section 4.7 — named, sweepable)

| Constant | Value | Sweep range for ablation | Rationale |
|---|---|---|---|
| `MASTERY_GRACE_ATTEMPTS` | 1 | 0, 1, 2 | One extra attempt at each tier before escalating, for a student who has already shown mastery on this topic elsewhere. |
| `ERROR_REPEAT_N` | 2 | 2, 3 | Same conceptual error type on this and the previous attempt is enough to call it "stable," per the task's own skeleton. |
| `ESCALATION_MAX_BUMP` | 1 | fixed | Caps the depth-driven jump to one level per decision — prevents a single high-severity signal from skipping straight to the solution template. |
| `QUERY_SIMILARITY_THRESHOLD` | 0.95 | 0.85–0.95 | Reuses the `SequenceMatcher` + `_normalize_sql`-style idiom already established in `guardrails.py`'s leakage check, at a stricter threshold (near-identical, not "similar"). |
| `DWELL_MIN_SECONDS` | 15.0 | 10–30 | Below this, a resubmission is implausible to reflect having read a hint. |

Topic mastery groups in the current catalog are n=2–4 (Practice *k* / Assignment *k* pairs
sharing one `Problem.topic` string verbatim) — the grace mechanism is real but should be reported
as low-n in the thesis, not implied to generalize across a larger topic taxonomy.

## 6. Non-goals carried forward

Per the original task's §8: grading logic and the 11-category error taxonomy are unchanged;
`LEVEL_DESCRIPTIONS` / `_build_hint_prompt` content is unchanged; no dashboard UI is built, only
the trace it will consume; no ML-trained policy — this is a rule-based decision function.
