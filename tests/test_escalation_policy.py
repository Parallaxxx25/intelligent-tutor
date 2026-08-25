"""
Unit tests for backend/agents/escalation_policy.py — pure, no DB, no LLM.

Structure:
  - TestDegenerateCase: signals with only attempt_count set must reproduce
    attempt_count_floor exactly (functional requirement #5, fallback path).
  - One Test* class per driver, exercised in isolation.
  - TestMultiSignalScenarios: realistic sequences combining several drivers.
"""

from __future__ import annotations

from backend.agents.escalation_policy import (
    DWELL_MIN_SECONDS,
    EscalationSignals,
    attempt_count_floor,
    decide_hint_level,
)

STARTER = "-- Write your query here\n"


class TestDegenerateCase:
    def test_matches_attempt_count_floor_when_no_other_signals(self) -> None:
        for attempt in range(1, 7):
            signals = EscalationSignals(attempt_count=attempt)
            decision = decide_hint_level(signals)
            assert decision.level == attempt_count_floor(attempt)
            assert decision.drivers == ()
            assert decision.policy_version == "v2"

    def test_floor_clamps_at_4(self) -> None:
        assert attempt_count_floor(99) == 4

    def test_floor_clamps_at_1(self) -> None:
        assert attempt_count_floor(0) == 1
        assert attempt_count_floor(-5) == 1


class TestMasteryGrace:
    def test_no_grace_without_advanced_or_expert_mastery(self) -> None:
        signals = EscalationSignals(attempt_count=3, topic_mastery="intermediate")
        decision = decide_hint_level(signals)
        assert decision.level == 3
        assert "topic_mastery_grace" not in decision.drivers

    def test_grace_shifts_ladder_right_on_attempt_2(self) -> None:
        signals = EscalationSignals(attempt_count=2, topic_mastery="advanced")
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert "topic_mastery_grace" in decision.drivers

    def test_grace_is_a_true_noop_on_attempt_1(self) -> None:
        """Level 1 is already the floor -- nothing to shift down to, so the
        driver must not fire (would be a misleading trace entry)."""
        signals = EscalationSignals(attempt_count=1, topic_mastery="expert")
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert "topic_mastery_grace" not in decision.drivers

    def test_stuck_mastered_student_still_reaches_level_4(self) -> None:
        """Grace delays escalation, never withholds it (Wood/Bruner/Ross:
        reduced support, not punitive)."""
        signals = EscalationSignals(attempt_count=5, topic_mastery="expert")
        decision = decide_hint_level(signals)
        assert decision.level == 4


class TestDepthBump:
    def test_blocking_error_escalates_immediately(self) -> None:
        signals = EscalationSignals(attempt_count=1, error_type="timeout_error")
        decision = decide_hint_level(signals)
        assert decision.level == 2
        assert "blocking_error_escalation" in decision.drivers

    def test_conceptual_error_repeated_twice_escalates(self) -> None:
        signals = EscalationSignals(
            attempt_count=1,
            error_type="join_error",
            error_type_history=("join_error", "join_error"),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 2
        assert "error_type_stable_2x" in decision.drivers

    def test_conceptual_error_seen_once_does_not_escalate(self) -> None:
        signals = EscalationSignals(
            attempt_count=1,
            error_type="join_error",
            error_type_history=("join_error",),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert decision.drivers == ()

    def test_shallow_error_never_bumps_even_if_repeated(self) -> None:
        """Sweller: a typo repeated isn't evidence of deep confusion."""
        signals = EscalationSignals(
            attempt_count=1,
            error_type="syntax_error",
            error_type_history=("syntax_error", "syntax_error"),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert decision.drivers == ()

    def test_conceptual_error_alternating_with_different_type_does_not_escalate(self) -> None:
        """Flailing (different error each attempt) doesn't earn the 'stable'
        driver -- it isn't stuck on one concept."""
        signals = EscalationSignals(
            attempt_count=1,
            error_type="join_error",
            error_type_history=("column_error", "join_error"),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert decision.drivers == ()

    def test_bump_is_capped_at_one_level(self) -> None:
        signals = EscalationSignals(attempt_count=4, error_type="timeout_error")
        decision = decide_hint_level(signals)
        assert decision.level == 4  # already at ceiling; bump can't exceed it


class TestFastResubmitHold:
    def _base_kwargs(self) -> dict:
        return dict(
            attempt_count=3,
            error_type="join_error",
            error_type_history=("join_error", "join_error"),
            query_history=("SELECT bad FROM t",),
            hint_level_history=(2,),
            current_query="SELECT bad FROM t",
        )

    def test_fast_identical_resubmit_holds_at_previous_level(self) -> None:
        signals = EscalationSignals(
            **self._base_kwargs(), seconds_since_prev=5.0
        )
        decision = decide_hint_level(signals)
        # Without the hold this would bump to 4 (join_error stable 2x from floor 3).
        assert decision.level == 2
        assert "query_unchanged_fast_hold" in decision.drivers
        # The would-have-escalated driver is still logged for the trace.
        assert "error_type_stable_2x" in decision.drivers

    def test_slow_identical_resubmit_does_not_hold(self) -> None:
        signals = EscalationSignals(
            **self._base_kwargs(), seconds_since_prev=DWELL_MIN_SECONDS + 30
        )
        decision = decide_hint_level(signals)
        assert decision.level == 4
        assert "query_unchanged_fast_hold" not in decision.drivers

    def test_fast_but_different_query_does_not_hold(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["current_query"] = "SELECT completely_different_thing FROM other_table WHERE x"
        signals = EscalationSignals(**kwargs, seconds_since_prev=5.0)
        decision = decide_hint_level(signals)
        assert decision.level == 4
        assert "query_unchanged_fast_hold" not in decision.drivers

    def test_no_hold_without_prior_hint_level(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["hint_level_history"] = ()
        signals = EscalationSignals(**kwargs, seconds_since_prev=5.0)
        decision = decide_hint_level(signals)
        assert decision.level == 4
        assert "query_unchanged_fast_hold" not in decision.drivers


class TestUnpromptedClamp:
    def test_empty_query_on_first_attempt_clamps_to_1(self) -> None:
        signals = EscalationSignals(
            attempt_count=1, current_query="", starter_code=STARTER
        )
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert "unprompted_hint_request" in decision.drivers
        assert "unprompted_level_1_clamp" in decision.drivers

    def test_starter_code_verbatim_clamps_to_1(self) -> None:
        signals = EscalationSignals(
            attempt_count=1, current_query=STARTER, starter_code=STARTER
        )
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert "unprompted_level_1_clamp" in decision.drivers

    def test_blank_resubmit_after_genuine_attempt_is_logged_not_clamped(self) -> None:
        """A student who already earned Level 3 through real attempts and
        then blanks the box for a fresh hint isn't demoted -- would
        contradict the no-mid-problem-regression rule."""
        signals = EscalationSignals(
            attempt_count=4,
            current_query="",
            starter_code=STARTER,
            query_history=("SELECT first_name FROM sales.customers",),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 4
        assert "unprompted_hint_request" in decision.drivers
        assert "unprompted_level_1_clamp" not in decision.drivers

    def test_genuine_query_is_not_flagged_unprompted(self) -> None:
        signals = EscalationSignals(
            attempt_count=1,
            current_query="SELECT * FROM sales.customers",
            starter_code=STARTER,
        )
        decision = decide_hint_level(signals)
        assert "unprompted_hint_request" not in decision.drivers


class TestMultiSignalScenarios:
    def test_stuck_on_one_concept_escalates_across_attempts(self) -> None:
        """Same conceptual error, 3 attempts in a row -- should reach a
        higher level than plain attempt count alone by attempt 2."""
        signals = EscalationSignals(
            attempt_count=2,
            error_type="aggregation_error",
            error_type_history=("aggregation_error", "aggregation_error"),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 3  # floor 2 + bump 1
        assert "error_type_stable_2x" in decision.drivers

    def test_flailing_stays_near_the_floor(self) -> None:
        """A different shallow/conceptual error every attempt never
        satisfies the 'stable' condition -- no driver fires."""
        signals = EscalationSignals(
            attempt_count=3,
            error_type="subquery_error",
            error_type_history=("column_error", "aggregation_error"),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 3
        assert decision.drivers == ()

    def test_mastered_topic_with_genuine_struggle_still_reaches_ceiling(self) -> None:
        """At attempt 4, grace visibly lowers the floor (3 instead of 4) but
        the repeated conceptual error still bumps it right back to the
        ceiling -- grace delays, genuine struggle still gets full support."""
        signals = EscalationSignals(
            attempt_count=4,
            topic_mastery="advanced",
            error_type="logic_error",
            error_type_history=("logic_error", "logic_error"),
        )
        decision = decide_hint_level(signals)
        assert decision.level == 4
        assert "topic_mastery_grace" in decision.drivers
        assert "error_type_stable_2x" in decision.drivers

    def test_spammer_never_escalates_past_first_shown_level(self) -> None:
        """Repeated fast, unchanged resubmission holds regardless of how
        high attempt_count climbs."""
        signals = EscalationSignals(
            attempt_count=8,
            error_type="join_error",
            error_type_history=("join_error", "join_error"),
            query_history=("SELECT x FROM y",),
            hint_level_history=(1,),
            current_query="SELECT x FROM y",
            seconds_since_prev=3.0,
        )
        decision = decide_hint_level(signals)
        assert decision.level == 1
        assert "query_unchanged_fast_hold" in decision.drivers

    def test_rationale_is_human_readable_and_reflects_drivers(self) -> None:
        signals = EscalationSignals(attempt_count=1, error_type="timeout_error")
        decision = decide_hint_level(signals)
        assert "blocking_error_escalation" in decision.rationale()
        assert decision.policy_version in decision.rationale()

    def test_as_dict_is_json_serializable_shape(self) -> None:
        import json

        signals = EscalationSignals(attempt_count=2, topic_mastery="advanced")
        decision = decide_hint_level(signals)
        json.dumps(decision.as_dict())  # must not raise
