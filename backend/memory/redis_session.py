"""
Redis Session Manager — Short-term memory for student-problem attempts.

Stores state including:
  - attempt count
  - past hint levels given
  - recent error patterns
  - start of the session timestamp

Sessions are Redis hashes (not JSON blobs): ``update_session`` writes with a
single HSET, so a merge is one atomic server-side op instead of a
client-side read-modify-write race between concurrent submissions.

Managed via a singleton instance connected during app lifespan.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import redis.asyncio as redis
from redis.exceptions import RedisError

from backend.config import get_settings

logger = logging.getLogger(__name__)

# Fields that may be absent from a session hash but must round-trip as the
# right type once read back (Redis hashes store everything as strings).
_INT_FIELDS = {"attempts", "last_hint_level"}


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

    @staticmethod
    def _coerce(data: dict[str, Any]) -> dict[str, Any]:
        """Cast hash-stored strings back to int for known numeric fields."""
        out: dict[str, Any] = dict(data)
        for field in _INT_FIELDS:
            if field in out and out[field] not in (None, ""):
                try:
                    out[field] = int(out[field])
                except (TypeError, ValueError):
                    pass
        return out

    async def get_session(self, user_id: int, problem_id: int) -> dict[str, Any]:
        """Load session data for a user-problem pair."""
        client = await self._get_client()
        if client is None:
            logger.warning("Redis unavailable. Returning empty session.")
            return {}

        key = self._get_key(user_id, problem_id)
        try:
            data = await client.hgetall(key)
            return self._coerce(data) if data else {}
        except RedisError as e:
            logger.error("Error fetching session from Redis: %s", e)
            self._client = None  # force reconnect attempt next call
            return {}

    async def update_session(self, user_id: int, problem_id: int, data: dict[str, Any]) -> bool:
        """Merge fields into a session hash, atomically, in one round trip."""
        client = await self._get_client()
        if client is None:
            return False

        key = self._get_key(user_id, problem_id)
        # Redis hashes can't hold None; drop unset fields rather than erroring.
        fields = {k: v for k, v in data.items() if v is not None}
        if not fields:
            return True

        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.hset(key, mapping=fields)
                pipe.expire(key, self.ttl)
                await pipe.execute()
            return True
        except RedisError as e:
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
        except RedisError as e:
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
        except RedisError as e:
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
        except RedisError:
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
