"""
Read-only queries feeding the escalation policy's signals (see
docs/hint-escalation-policy-v2.md). Shared by ``routes.py`` (/api/submit)
and ``v1_routes.py`` (/api/v1/hint) so the two API surfaces build
EscalationSignals from identical data.

Deliberately separate from backend/agents/escalation_policy.py: that
module is pure (no I/O) so it can be unit-tested and ablated without a
database; these functions are the only place that touches Postgres for
this feature.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import InteractionHistory, MasteryLevel, Problem, StudentProgress


class AttemptRecord(TypedDict):
    error_type: str | None
    submitted_code: str
    hint_level: int | None
    timestamp: datetime


async def get_attempt_history(
    db: AsyncSession,
    user_id: int,
    problem_id: int,
    limit: int = 5,
    exclude_interaction_id: int | None = None,
) -> list[AttemptRecord]:
    """
    This student's last ``limit`` attempts on this Problem, oldest first.

    The escalation policy's error_type_history, query_history,
    hint_level_history, and seconds_since_prev all derive from this one
    read of ``interaction_history`` — no new columns, no Redis fields
    (see ADR-0005: interaction_history is authoritative, not Redis).

    ``exclude_interaction_id``: on ``/api/v1``, the current submission's
    row is already committed (by ``/grade``, before ``/hint`` runs) with
    ``error_type``/``hint_level`` still unset — without excluding it here,
    it would appear as its own "most recent prior attempt", corrupting the
    query-unchanged and error-type-stable checks. ``/api/submit`` never
    needs this: there, this row doesn't exist yet when history is read.
    """
    filters = [
        InteractionHistory.user_id == user_id,
        InteractionHistory.problem_id == problem_id,
    ]
    if exclude_interaction_id is not None:
        filters.append(InteractionHistory.id != exclude_interaction_id)

    result = await db.execute(
        select(
            InteractionHistory.error_type,
            InteractionHistory.submitted_code,
            InteractionHistory.hint_level,
            InteractionHistory.timestamp,
        )
        .where(*filters)
        .order_by(InteractionHistory.id.desc())
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "error_type": error_type.value if error_type else None,
            "submitted_code": submitted_code,
            "hint_level": hint_level,
            "timestamp": timestamp,
        }
        for error_type, submitted_code, hint_level, timestamp in reversed(rows)
    ]


def seconds_since_last_attempt(history: list[AttemptRecord]) -> float | None:
    """Wall-clock gap between the most recent attempt and now, or None if
    this is the student's first attempt (nothing to measure dwell against)."""
    if not history:
        return None
    last = history[-1]["timestamp"]
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds()


async def get_topic_mastery(
    db: AsyncSession, user_id: int, problem_id: int
) -> MasteryLevel | None:
    """
    Highest MasteryLevel this student has reached on any OTHER problem
    sharing the current problem's exact ``Problem.topic`` string.

    Practice-k and Assignment-k rows share that string verbatim (seed.py
    assigns both from the same CSV row), so this groups on the designed
    practice/assignment pair — see docs/hint-escalation-policy-v2.md §3 for
    why topic grouping is *not* normalized further. None if this is the
    student's first problem in the topic (nothing to grant grace from).
    """
    topic_result = await db.execute(select(Problem.topic).where(Problem.id == problem_id))
    topic = topic_result.scalar_one_or_none()
    if topic is None:
        return None

    result = await db.execute(
        select(StudentProgress.mastery_level)
        .join(Problem, Problem.id == StudentProgress.problem_id)
        .where(
            StudentProgress.user_id == user_id,
            Problem.topic == topic,
            StudentProgress.problem_id != problem_id,
        )
    )
    levels = [lvl for lvl in result.scalars().all() if lvl is not None]
    if not levels:
        return None

    order = list(MasteryLevel)
    return max(levels, key=order.index)
