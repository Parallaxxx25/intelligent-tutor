# Hint-level escalation moves from attempt-count-only to a multi-signal policy, sourced from Postgres

We replaced the single-signal rule (`attempt 1→L1, 2→L2, 3→L3, 4+→L4`, duplicated in four
places) with a pure decision function in `backend/agents/escalation_policy.py` that also
considers error-type stability, query-diff against the previous attempt, submission dwell time,
and topic mastery. Full rationale in
[hint-escalation-policy-v2.md](../hint-escalation-policy-v2.md).

Two decisions inside that change are hard to reverse and worth recording separately from the
methodology doc:

**All new escalation state is read from `interaction_history` (Postgres), not stored in the
Redis session.** ADR-0004 already established that `student_progress.attempts` in Postgres is
authoritative for hint-level escalation specifically so a Redis restart mid-lab can't reset a
student to Level 1. Extending `SessionManager` with `error_type_history` / `query_history` /
`hint_level_history` would have reintroduced exactly the failure mode 0004 closed off, and would
have duplicated data `interaction_history` already stores per attempt (submitted_code, error_type,
hint_level, timestamp). We add two read-only queries instead (`_attempt_history`,
`_topic_mastery`); Redis's job doesn't change.

**Severity is derived from a deterministic map on `error_type`, not read from
`DiagnosisResult.severity`.** The rule-based classifier assigns `"medium"` to 9 of its 11 error
types — as a signal it is nearly constant in the deterministic and LangGraph pipelines. In the
LLM pipeline, severity comes from Gemini, which would make the escalation *arithmetic*
non-reproducible and untestable without mocking an LLM call — the opposite of what "pure,
deterministic, unit-testable" (the task's own requirement) means. `ERROR_DEPTH` maps the
existing 11-category taxonomy to shallow/conceptual/blocking instead, giving Sweller's
noise-vs-signal distinction a fixed, citable, testable source. Gemini's severity/level is still
recorded in the trace (`llm_proposed_level`) as a reportable agreement-rate datum, just not used
in the decision.

Rejected alternative: keep `severity` as the depth signal and accept that 2 of 3 pipelines carry
a dead driver. Rejected because the ablation study (Phase 4) would then be measuring nothing on
those two arms, undermining the pipeline-comparison the thesis evaluation section depends on.
