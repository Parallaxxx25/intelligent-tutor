"""
Adaptive hint-level escalation policy (v2).

Pure, deterministic, no I/O and no LLM call — see
docs/hint-escalation-policy-v2.md for the full constraint-to-mechanism
mapping and docs/adr/0005-multi-signal-hint-escalation.md for why this
lives in its own module rather than inside hint_generator.py or
supervisor.py.

``attempt_count_floor`` is the old (pre-v2) rule, kept verbatim as the
documented fallback: with only ``attempt_count`` populated, every other
signal is empty/None and ``decide_hint_level`` degenerates to exactly
this floor (see test_escalation_policy.py::test_degenerate_case).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# Named constants (sweepable in the ablation study — see run_ablation.py)
# ---------------------------------------------------------------------------

POLICY_VERSION = "v2"

MASTERY_GRACE_ATTEMPTS = 1
ERROR_REPEAT_N = 2
ESCALATION_MAX_BUMP = 1
QUERY_SIMILARITY_THRESHOLD = 0.95
DWELL_MIN_SECONDS = 15.0
DEESCALATING_MASTERY = ("advanced", "expert")

# Sweller (1988): a shallow slip (typo, wrong table name) isn't evidence of
# deep confusion and shouldn't escalate on its own; a conceptual error
# repeated, or a blocking one, is. Deliberately keyed on the *existing*
# ErrorType taxonomy (see CLAUDE.md) rather than the classifier's `severity`
# field, which is near-constant ("medium") for 9 of 11 branches and, in the
# LLM pipeline, LLM-sourced — see ADR-0005 for why that disqualifies it as
# the depth signal.
ERROR_DEPTH: dict[str, str] = {
    "syntax_error": "shallow",
    "column_error": "shallow",
    "relation_error": "shallow",
    "ambiguity_error": "shallow",
    "type_error": "shallow",
    "runtime_error": "shallow",
    "join_error": "conceptual",
    "aggregation_error": "conceptual",
    "subquery_error": "conceptual",
    "logic_error": "conceptual",
    "timeout_error": "blocking",
}


def attempt_count_floor(attempt_count: int) -> int:
    """The pre-v2 rule: attempt 1->1, 2->2, 3->3, 4+->4. Kept as the
    explicit fallback (functional requirement #5) and as the floor every
    v2 decision starts from."""
    return min(max(attempt_count, 1), 4)


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _query_unchanged(current: str, previous: str) -> bool:
    if not current or not previous:
        return False
    ratio = SequenceMatcher(None, _normalize(current), _normalize(previous)).ratio()
    return ratio >= QUERY_SIMILARITY_THRESHOLD


def _is_unprompted(query: str, starter_code: str | None) -> bool:
    normalized = _normalize(query)
    return normalized == "" or normalized == _normalize(starter_code or "")


def _clamp(level: int, lo: int = 1, hi: int = 4) -> int:
    return max(lo, min(hi, level))


# ---------------------------------------------------------------------------
# Signals / Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationSignals:
    """Everything decide_hint_level needs, already resolved by the caller
    (routes.py / v1_routes.py) from Postgres — this module does no I/O.

    Only ``attempt_count`` is required; every other field defaults to
    "no information available", which is what makes the degenerate case
    (fresh session, cold start) reduce to ``attempt_count_floor``.
    """

    attempt_count: int
    error_type: str | None = None
    error_type_history: tuple[str | None, ...] = field(default_factory=tuple)
    query_history: tuple[str, ...] = field(default_factory=tuple)
    hint_level_history: tuple[int, ...] = field(default_factory=tuple)
    seconds_since_prev: float | None = None
    topic_mastery: str | None = None
    # None = "caller didn't supply this" -> skip the unprompted-request
    # check entirely. "" is a real, meaningful value (a genuinely blank
    # submission) and must not be confused with "unknown" -- production
    # callers always pass the actual submitted code, never None.
    current_query: str | None = None
    starter_code: str | None = None


@dataclass(frozen=True)
class EscalationDecision:
    level: int
    drivers: tuple[str, ...]
    policy_version: str
    signals_summary: dict

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "drivers": list(self.drivers),
            "policy_version": self.policy_version,
            "signals": self.signals_summary,
        }

    def rationale(self) -> str:
        if not self.drivers:
            return f"Level {self.level} from attempt count alone (policy {self.policy_version})."
        return (
            f"Level {self.level} (policy {self.policy_version}): "
            + "; ".join(self.drivers)
            + "."
        )


# ---------------------------------------------------------------------------
# Decision function
# ---------------------------------------------------------------------------


def decide_hint_level(signals: EscalationSignals) -> EscalationDecision:
    """
    Fixed-order, non-order-dependent multi-signal decision:

      1. Floor      — attempt count, shifted right by a mastery grace period
                       (Wood, Bruner & Ross: support withdrawn as competence
                       increases; ZPD: still tracks *this* problem's attempts).
      2. Bump        — at most ESCALATION_MAX_BUMP, only for conceptual/
                       blocking errors (Sweller: don't escalate on noise).
      3. Hold        — overrides the bump when a fast, near-identical
                       resubmission suggests the hint wasn't read
                       (Fan et al. 2024).
      4. Unprompted  — clamps to Level 1 on a genuinely first, empty/
                       starter-code submission (cognitive-offloading proxy).

    See docs/hint-escalation-policy-v2.md §2 for the full citation mapping.
    """
    drivers: list[str] = []

    # --- 1. Floor: ZPD via attempt count, mastery grace shifts it right ---
    grace = MASTERY_GRACE_ATTEMPTS if signals.topic_mastery in DEESCALATING_MASTERY else 0
    level = attempt_count_floor(signals.attempt_count - grace)
    if grace and level < attempt_count_floor(signals.attempt_count):
        drivers.append("topic_mastery_grace")

    # --- 2. Bump: depth-aware escalation, capped ---
    depth = ERROR_DEPTH.get(signals.error_type or "", "shallow")
    error_repeated = (
        len(signals.error_type_history) >= ERROR_REPEAT_N
        and signals.error_type is not None
        and all(
            e == signals.error_type
            for e in signals.error_type_history[-ERROR_REPEAT_N:]
        )
    )
    if depth == "blocking":
        level = min(level + ESCALATION_MAX_BUMP, 4)
        drivers.append("blocking_error_escalation")
    elif depth == "conceptual" and error_repeated:
        level = min(level + ESCALATION_MAX_BUMP, 4)
        drivers.append(f"error_type_stable_{ERROR_REPEAT_N}x")

    # --- 3. Hold: fast + unchanged resubmission overrides the bump ---
    if (
        signals.hint_level_history
        and signals.query_history
        and _query_unchanged(signals.current_query, signals.query_history[-1])
        and signals.seconds_since_prev is not None
        and signals.seconds_since_prev < DWELL_MIN_SECONDS
    ):
        level = signals.hint_level_history[-1]
        drivers.append("query_unchanged_fast_hold")

    # --- 4. Unprompted: cognitive-offloading proxy ---
    if signals.current_query is not None and _is_unprompted(
        signals.current_query, signals.starter_code
    ):
        drivers.append("unprompted_hint_request")
        has_prior_genuine_attempt = any(
            not _is_unprompted(q, signals.starter_code) for q in signals.query_history
        )
        if not has_prior_genuine_attempt:
            level = 1
            drivers.append("unprompted_level_1_clamp")

    level = _clamp(level)

    return EscalationDecision(
        level=level,
        drivers=tuple(drivers),
        policy_version=POLICY_VERSION,
        signals_summary={
            "attempt_count": signals.attempt_count,
            "error_type": signals.error_type,
            "depth": depth,
            "topic_mastery": signals.topic_mastery,
            "grace_applied": bool(grace and "topic_mastery_grace" in drivers),
            "seconds_since_prev": signals.seconds_since_prev,
        },
    )
