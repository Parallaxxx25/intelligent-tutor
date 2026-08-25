# Changelog: Attempt-Count Hint Escalation → Multi-Signal Escalation Policy (v2)

For direct use in the thesis Methodology / System Design section. Full
constraint-to-mechanism rationale in
[hint-escalation-policy-v2.md](hint-escalation-policy-v2.md); the two
hardest-to-reverse decisions are recorded separately in
[ADR-0005](adr/0005-multi-signal-hint-escalation.md).

| # | Old behavior (v1) | New behavior (v2) | Citation |
|---|---|---|---|
| 1 | Hint level was a fixed schedule: attempt 1→L1, 2→L2, 3→L3, 4+→L4, independent of anything about the error itself. | Level is a function of the learner's current state: an attempt-count floor, adjusted by error depth, resubmission behavior, and topic mastery. | Vygotsky (1978), Zone of Proximal Development; VanLehn (2011), Ma et al. (2014), Steenbergen-Hu & Cooper (2014) on rigid step-logic underperforming human tutors. |
| 2 | No de-escalation mechanism existed anywhere in the system. | A student already ADVANCED/EXPERT on a sibling problem sharing the same `Problem.topic` gets a one-attempt grace period before escalating on a *new* problem in that topic — support delayed, never withheld (a stuck student still reaches L4, one attempt later). | Wood, Bruner & Ross (1976): scaffolding is "progressively withdrawn as competence increases." |
| 3 | Every error type escalated identically on repetition — a repeated typo counted the same as a repeated conceptual gap. | Only errors classified `conceptual` or `blocking` (join/aggregation/subquery/logic/timeout) escalate on repetition; `shallow` errors (syntax/column/relation/ambiguity/type/runtime) never bump the level, however many times they recur. | Sweller (1988), Cognitive Load Theory: don't escalate on noise; protect germane load. |
| 4 | A fast, near-identical resubmission was scored as "another attempt" and pushed the level up. | Held at the previously shown level when the resubmission is near-identical *and* arrives within 15s of the prior one — read as evidence the hint wasn't read, not that a stronger one is needed. A slow, unchanged resubmission (the hint *was* read, the student is still stuck) is allowed to escalate normally. | Fan et al. (2024), metacognitive laziness / cognitive offloading. |
| 5 | An empty or starter-code submission (effectively "just give me a hint") was graded like any other attempt and could inherit whatever level the attempt count implied. | Detected as `unprompted_hint_request` (always logged, for the future teacher dashboard); clamped to Level 1 only on the student's first genuine attempt on the problem — a student who already earned a higher level through real attempts isn't demoted for blanking the box once. | Fan et al. (2024): premature assistance should prompt independent effort first, not reward asking. |
| 6 | The chosen level was a bare integer — no record of why. | Every decision returns a structured `EscalationDecision` (`level`, `drivers`, `policy_version`, `signals`), persisted as `DiagnosisResult.escalation_trace` in `interaction_history.diagnosis_details`. | Holstein, McLaren & Aleven (2019): AI decisions in the classroom must be interpretable and overridable by a human. |
| 7 | The LLM pipeline clamped Gemini's suggested level downward against the attempt count (`min(gemini_level, attempt_derived_level)`) — an ad hoc, one-directional rule with no record of what Gemini actually proposed. | The multi-signal policy is fully authoritative over the level served; Gemini's own proposal is recorded in the trace as `llm_proposed_level` — a reportable agreement-rate datum for the thesis — but never used in the arithmetic. | ADR-0005; original task requirement that escalation arithmetic must not depend on an LLM to be reproducible. |
| 8 | The attempt-count rule was hand-duplicated in four places (`hint_generator.py`, `supervisor.py` ×2, `diagnostician.py`), each free to drift. | One module, `backend/agents/escalation_policy.py`, called from all three pipelines (deterministic, LangGraph, LLM). The old rule survives as `attempt_count_floor` — the documented, tested fallback when no richer signal is available (cold start, a caller that only has `attempt_count`). | Original task requirement: the old policy becomes the explicit fallback branch, not discarded code. |
| 9 | No artifact existed comparing the old policy's behavior to any alternative. | `backend/evaluation/run_ablation.py` replays five synthetic sessions (stuck-on-one-concept, flailing, fast-resubmit spammer, mastered topic, typo-then-conceptual) through both `attempt_count_floor` and `decide_hint_level` side by side, `policy_version`-tagged, markdown or CSV. | Deterministic-vs-adaptive comparison as the thesis evaluation artifact. |
| 10 | The eval harness's "Hint Level Compliance" metric scored generated hints against a hand-set `hint_level` that encoded the v1 rule (one sample — `timeout_01` — was in fact mislabeled under v1 conventions). | The dataset's expected level is asserted against the policy's own output (`decide_hint_level`), not a hand label; both eval harnesses (RAGAS-based and OpenRouter LLM-judge) stamp every generated report with `policy_version` so pre-v2 and v2 results can never be silently conflated. | Requirement to keep dataset and code from drifting apart, and to version-tag results for reporting. |

## What did not change

Per the original task's non-goals: grading logic (`run_sql_tests`), the
11-category `ErrorType` taxonomy, the four `LEVEL_DESCRIPTIONS` content
contracts and `_build_hint_prompt`, and the No Solution Leakage guardrail
content rules are all untouched — verified by a dedicated regression test
(`TestNoSolutionLeakageUnaffectedByEscalationLevel`) forcing every level
1–4 through the unchanged rule-based generators.
