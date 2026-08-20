"""
Redis Session Manager — Short-term memory for student-problem attempts.

Stores state including:
  - attempt count
  - past hint levels given
  - recent error patterns
  - start of the session timestamp

Sessions are Redis hashes (not JSON blobs): ``update_session`` merges with a
single HSET, so a merge is one atomic server-side op instead of a
client-side read-modify-write race between concurrent submissions.

Values come back as strings (Redis hashes are stringly-typed); callers that
need a number cast at the call site.

Managed via a singleton instance connected during app lifespan. Every
operation swallows *all* exceptions, not just RedisError: the cached
connection is bound to the event loop that opened it, so a second loop
(tests, a restarted worker) surfaces raw AttributeError/OSError from the
dead transport. Sessions are best-effort — a broken Redis must degrade to
stateless grading, never fail a submission.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import redis.asyncio as redis

from backend.config import get_settings

logger = logging.getLogger(__name__)


class SessionManager:
    """Async session manager using Redis, backed by hash-per-session storage."""

    def __init__(
        self,
        url: str,
        ttl: int = 86400,
        socket_timeout: float = 3.0,
        socket_connect_timeout: float = 3.0,
    ) -> None:
        self.url = url
        self.ttl = ttl
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis server (safe to call again after a drop)."""
        if self._client is not None:
            return
        try:
            client = redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=self.socket_connect_timeout,
                socket_timeout=self.socket_timeout,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            await client.ping()
            self._client = client
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

    async def _get_client(self) -> Optional[redis.Redis]:
        """Return a live client, transparently reconnecting after a drop."""
        if self._client is None:
            await self.connect()
        return self._client

    def _get_key(self, user_id: int, problem_id: int) -> str:
        """Generate a standard Redis key for a session."""
        return f"session:{user_id}:{problem_id}"

    async def get_session(self, user_id: int, problem_id: int) -> dict[str, Any]:
        """Load session data for a user-problem pair. All values are strings."""
        client = await self._get_client()
        if client is None:
            logger.warning("Redis unavailable. Returning empty session.")
            return {}

        key = self._get_key(user_id, problem_id)
        try:
            return await client.hgetall(key) or {}
        except Exception as e:
            logger.error("Error fetching session from Redis: %s", e)
            self._client = None  # force reconnect attempt next call
            return {}

    async def update_session(self, user_id: int, problem_id: int, data: dict[str, Any]) -> bool:
        """Merge fields into a session hash, then refresh its TTL."""
        client = await self._get_client()
        if client is None:
            return False

        key = self._get_key(user_id, problem_id)
        # Redis hashes can't hold None; drop unset fields rather than erroring.
        fields = {k: v for k, v in data.items() if v is not None}
        if not fields:
            return True

        try:
            await client.hset(key, mapping=fields)
            await client.expire(key, self.ttl)
            return True
        except Exception as e:
            logger.error("Error updating session in Redis: %s", e)
            self._client = None
            return False

    async def clear_session(self, user_id: int, problem_id: int) -> bool:
        """Delete a session (e.g., when the problem is solved)."""
        client = await self._get_client()
        if client is None:
            return False

        key = self._get_key(user_id, problem_id)
        try:
            await client.delete(key)
            return True
        except Exception as e:
            logger.error("Error clearing session from Redis: %s", e)
            self._client = None
            return False

    async def clear_user_sessions(self, user_id: int) -> int:
        """Delete every session hash for a user. Returns count deleted."""
        client = await self._get_client()
        if client is None:
            return 0

        deleted = 0
        try:
            async for key in client.scan_iter(match=f"session:{user_id}:*"):
                await client.delete(key)
                deleted += 1
        except Exception as e:
            logger.error("Error clearing user sessions from Redis: %s", e)
            self._client = None
        return deleted

    async def ping(self) -> bool:
        """Health-check helper: True if Redis answers, reconnecting first if needed."""
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.ping()
            return True
        except Exception:
            self._client = None
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
