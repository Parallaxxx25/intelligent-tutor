"""
Tests for the Memory package (Redis sessions, mastery promotion).
"""

from __future__ import annotations

import fakeredis
import pytest

from backend.db.models import MasteryLevel, StudentProgress
from backend.memory.mastery import update_mastery
from backend.memory.redis_session import SessionManager


@pytest.mark.asyncio
async def test_session_manager_basic_ops():
    """get_session / update_session / clear_session against fakeredis."""
    manager = SessionManager(url="redis://localhost:6379/1")
    manager._client = fakeredis.FakeAsyncRedis(decode_responses=True)

    uid, pid = 999, 1

    # Initially empty
    assert await manager.get_session(uid, pid) == {}

    # Merge fields — values round-trip as strings (Redis hashes are stringly-typed)
    assert await manager.update_session(uid, pid, {"attempts": 1, "last_hint_level": 2})
    session = await manager.get_session(uid, pid)
    assert int(session["attempts"]) == 1
    assert int(session["last_hint_level"]) == 2

    # None values are dropped rather than erroring
    assert await manager.update_session(uid, pid, {"last_error_type": None})
    assert "last_error_type" not in await manager.get_session(uid, pid)

    # Clear
    await manager.clear_session(uid, pid)
    assert await manager.get_session(uid, pid) == {}


def _progress(level: MasteryLevel = MasteryLevel.NOVICE) -> StudentProgress:
    return StudentProgress(user_id=1, problem_id=101, mastery_level=level)


def test_mastery_promotes_on_score():
    progress = _progress()

    assert update_mastery(progress, score=0.5, attempts=1) == MasteryLevel.BEGINNER
    assert progress.mastery_level == MasteryLevel.BEGINNER

    # Skips INTERMEDIATE on a high score
    assert update_mastery(progress, score=0.9, attempts=2) == MasteryLevel.ADVANCED
    assert progress.mastery_level == MasteryLevel.ADVANCED


def test_mastery_never_demotes():
    progress = _progress(MasteryLevel.ADVANCED)

    assert update_mastery(progress, score=0.0, attempts=9) == MasteryLevel.ADVANCED
    assert update_mastery(progress, score=0.5, attempts=1) == MasteryLevel.ADVANCED
    assert progress.mastery_level == MasteryLevel.ADVANCED


def test_mastery_expert_needs_perfect_score_and_few_attempts():
    assert update_mastery(_progress(), score=1.0, attempts=2) == MasteryLevel.EXPERT
    # Perfect but slow — caps at ADVANCED
    assert update_mastery(_progress(), score=1.0, attempts=5) == MasteryLevel.ADVANCED


def test_mastery_tolerates_unflushed_progress_row():
    """A freshly constructed row has mastery_level=None until the DB default lands."""
    progress = StudentProgress(user_id=1, problem_id=101)
    assert progress.mastery_level is None
    assert update_mastery(progress, score=0.5, attempts=1) == MasteryLevel.BEGINNER
