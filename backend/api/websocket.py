"""
WebSocket endpoint for real-time tutoring session updates.

Phase 1: Stub implementation that broadcasts pipeline progress events.
Full implementation (with Redis pub/sub) deferred to Phase 3.

Version: 2026-02-12
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


# ---------------------------------------------------------------------------
# Connection manager (in-memory for Phase 1)
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages active WebSocket connections by session ID."""

    def __init__(self) -> None:
        self._active: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and register it."""
        await websocket.accept()
        self._active[session_id] = websocket
        logger.info("WebSocket connected: session=%s", session_id)

    def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection."""
        self._active.pop(session_id, None)
        logger.info("WebSocket disconnected: session=%s", session_id)

    async def send_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Send a JSON event to a specific session."""
        ws = self._active.get(session_id)
        if ws:
            await ws.send_json(event)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast a JSON event to all connected clients."""
        for ws in self._active.values():
            await ws.send_json(event)


manager = ConnectionManager()


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

    Phase 1: The client stays connected and receives keep-alive pings.
    The actual pipeline events are sent from the API routes layer.
    """
    await manager.connect(session_id, websocket)
    try:
        while True:
            # Wait for messages from client (e.g. heartbeat)
            data = await websocket.receive_text()
            logger.debug("WS %s received: %s", session_id, data)

            if data == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(session_id)
