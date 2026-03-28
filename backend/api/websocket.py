"""
WebSocket endpoint for real-time tutoring session updates.

Phase 3: Real-time event broadcasting using Redis Pub/Sub.

Version: 2026-03-28
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.memory.redis_session import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


# ---------------------------------------------------------------------------
# Connection manager (Redis Pub/Sub for Phase 3)
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections and integrates with Redis Pub/Sub."""

    def __init__(self) -> None:
        self._active: dict[str, WebSocket] = {}

    def _get_channel_name(self, session_id: str) -> str:
        return f"channel:session:{session_id}"

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and register it locally."""
        await websocket.accept()
        self._active[session_id] = websocket
        logger.info("WebSocket connected: session=%s", session_id)

    def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection locally."""
        self._active.pop(session_id, None)
        logger.info("WebSocket disconnected: session=%s", session_id)

    async def send_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Publish a JSON event to a specific session's Redis channel."""
        sm = get_session_manager()
        r = sm._client
        if r:
            channel = self._get_channel_name(session_id)
            try:
                await r.publish(channel, json.dumps(event))
            except Exception as e:
                logger.error("Failed to publish event to Redis: %s", e)
        else:
            # Fallback to in-memory delivery if Redis is unavailable
            ws = self._active.get(session_id)
            if ws:
                await ws.send_json(event)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast a JSON event to all connected clients."""
        for ws in self._active.values():
            try:
                await ws.send_json(event)
            except Exception:
                pass


manager = ConnectionManager()


async def subscribe_to_redis_channel(websocket: WebSocket, session_id: str) -> None:
    """Task that listens to the Redis channel and forwards messages to the WebSocket."""
    sm = get_session_manager()
    r = sm._client
    if not r:
        return

    channel_name = manager._get_channel_name(session_id)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(channel_name)
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    event = json.loads(data)
                    await websocket.send_json(event)
                except Exception as e:
                    logger.error("Error forwarding message to websocket: %s", e)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Redis pub/sub error for session %s: %s", session_id, e)
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.close()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/session/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str) -> None:
    """
    WebSocket endpoint for real-time session updates.

    Clients connect to receive progress events during code submission:
      - {"event": "grading_started"}
      - {"event": "grading_complete", "score": 0.75}
      - {"event": "diagnosis_complete", "error_type": "logic_error"}
      - {"event": "hint_ready", "hint_level": 2}
    """
    await manager.connect(session_id, websocket)
    sm = get_session_manager()

    # Run the Redis subscriber loop as a background task if Redis is active
    if sm._client:
        pubsub_task = asyncio.create_task(
            subscribe_to_redis_channel(websocket, session_id)
        )
    else:
        pubsub_task = None

    try:
        while True:
            # Wait for messages from client (e.g. heartbeat)
            data = await websocket.receive_text()
            logger.debug("WS %s received: %s", session_id, data)

            if data == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(session_id)
    finally:
        if pubsub_task:
            pubsub_task.cancel()
