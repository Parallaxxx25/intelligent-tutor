"""
Tests for the Memory package components (Redis, LTM, Mastery).
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, AsyncMock

import fakeredis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.redis_session import SessionManager
from backend.memory.mastery import MasteryTracker
from backend.db.models import StudentProgress, MasteryLevel

@pytest.mark.asyncio
async def test_dummy_at_top():
    assert 1 == 1

@pytest.mark.asyncio
async def test_a_session():
    """Test get_session, update_session, and clear_session using fakeredis."""
    # Setup fakeredis client
    fake_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    manager = SessionManager(url="redis://localhost:6379/1")
    manager._client = fake_client # Inject fake client

    user_id = 999
    prob_id = 1
    
    # 1. Initially empty
    s1 = await manager.get_session(user_id, prob_id)
    assert s1 == {}

    # 2. Update
    success = await manager.update_session(user_id, prob_id, {"attempts": 1, "hint": 1})
    assert success is True

    # 3. Retrieve
    s2 = await manager.get_session(user_id, prob_id)
    assert s2["attempts"] == 1
    assert s2["hint"] == 1

    # 4. Clear
    await manager.clear_session(user_id, prob_id)
    s3 = await manager.get_session(user_id, prob_id)
    assert s3 == {}

@pytest.mark.asyncio
async def test_mastery_tracker_level_escalation():
    """Test correctly escalating student mastery levels."""
    db_session = MagicMock(spec=AsyncSession)
    tracker = MasteryTracker()
    
    user_id = 1
    problem_id = 101
    
    # Mock progress existence
    mock_progress = StudentProgress(
        user_id=user_id,
        problem_id=problem_id,
        mastery_level=MasteryLevel.NOVICE
    )
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_progress
    db_session.execute = AsyncMock(return_value=mock_result)

    # NOVICE -> BEGINNER
    new_lvl = await tracker.update_mastery(db_session, user_id, problem_id, score=0.5, attempts=1)
    assert new_lvl == MasteryLevel.BEGINNER
    assert mock_progress.mastery_level == MasteryLevel.BEGINNER

    # BEGINNER -> ADVANCED (skip intermediate with high score)
    new_lvl = await tracker.update_mastery(db_session, user_id, problem_id, score=0.9, attempts=2)
    assert new_lvl == MasteryLevel.ADVANCED
    assert mock_progress.mastery_level == MasteryLevel.ADVANCED
