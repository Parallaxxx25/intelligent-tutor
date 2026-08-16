"""
API-key auth dependency.

Empty ``settings.API_KEY`` (the default) disables auth entirely — that's
local dev. Set API_KEY in .env for any deployment reachable outside
localhost; every caller must then send a matching ``X-API-Key`` header.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from backend.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: enforce X-API-Key when API_KEY is configured."""
    settings = get_settings()
    if not settings.API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header.",
        )
