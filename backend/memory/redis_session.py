"""
Redis Session Manager — Short-term memory for student-problem attempts.

Stores state including:
  - attempt count
  - past hint levels given
  - recent error patterns
  - start of the session timestamp

Managed via a singleton instance connected during app lifespan.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from backend.config import get_settings

logger = logging.getLogger(__name__)

class SessionManager:
    """Async session manager using Redis."""

    def __init__(self, url: str, ttl: int = 86400) -> None:
        self.url = url
        self.ttl = ttl
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis server."""
        if self._client is None:
            try:
                self._client = redis.from_url(
                    self.url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                # Test connection
                await self._client.ping()
                logger.info("Connected to Redis for sessions.")
            except Exception as e:
                logger.error("Failed to connect to Redis: %s", e)
                self._client = None

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Disconnected from Redis.")

    def _get_key(self, user_id: int, problem_id: int) -> str:
        """Generate a standard Redis key for a session."""
        return f"session:{user_id}:{problem_id}"

    async def get_session(self, user_id: int, problem_id: int) -> dict[str, Any]:
        """Load session data for a user-problem pair."""
        if not self._client:
            logger.warning("Redis client not connected. Returning empty session.")
            return {}

        key = self._get_key(user_id, problem_id)
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error("Error fetching session from Redis: %s", e)
        
        return {}

    async def update_session(self, user_id: int, problem_id: int, data: dict[str, Any]) -> bool:
        """Update/merge session data for a user-problem pair."""
        if not self._client:
            return False

        key = self._get_key(user_id, problem_id)
        try:
            # Atomic update (Read-Modify-Write)
            # In a highly concurrent environment, using a Lua script or WATCH would be better.
            # For this tutor app, a simple fetch-merge-save should be sufficient.
            existing = await self.get_session(user_id, problem_id)
            existing.update(data)
            
            await self._client.set(
                key,
                json.dumps(existing),
                ex=self.ttl,
            )
            return True
        except Exception as e:
            logger.error("Error updating session in Redis: %s", e)
            return False

    async def clear_session(self, user_id: int, problem_id: int) -> bool:
        """Delete a session (e.g., when the problem is solved)."""
        if not self._client:
            return False

        key = self._get_key(user_id, problem_id)
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error("Error clearing session from Redis: %s", e)
            return False

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_session_manager: Optional[SessionManager] = None

def get_session_manager() -> SessionManager:
    """Return the global SessionManager instance."""
    global _session_manager
    if _session_manager is None:
        settings = get_settings()
        _session_manager = SessionManager(
            url=settings.REDIS_URL,
            ttl=settings.REDIS_SESSION_TTL,
        )
    return _session_manager
