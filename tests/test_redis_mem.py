"""
Tests for Redis sessions.
"""

from __future__ import annotations

import pytest
import fakeredis
from backend.memory.redis_session import SessionManager

@pytest.mark.asyncio
async def test_session_manager_basic_ops():
    """Test get_session, update_session, and clear_session using fakeredis."""
    fake_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    manager = SessionManager(url="redis://localhost:6379/1")
    manager._client = fake_client # Inject fake client

    uid, pid = 123, 456
    
    # Empty
    assert await manager.get_session(uid, pid) == {}

    # Set
    assert await manager.update_session(uid, pid, {"foo": "bar"})
    
    # Get
    assert (await manager.get_session(uid, pid))["foo"] == "bar"

    # Clear
    await manager.clear_session(uid, pid)
    assert await manager.get_session(uid, pid) == {}
