"""
Retention purge — deletes InteractionHistory rows older than
``settings.INTERACTION_RETENTION_DAYS``.

Submitted SQL, grading details, and hint text are the sensitive payload in
this schema; StudentProgress/mastery rows are aggregates and are kept.

Not scheduled by the app itself (no cron/worker in this stack) — run
periodically out-of-band, e.g. a scheduled task calling:

    python -m backend.db.purge_expired

Idempotent — safe to run repeatedly or on an empty table.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import delete

from backend.config import get_settings
from backend.db.database import async_session_factory
from backend.db.models import InteractionHistory

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)


async def purge_expired_interactions(retention_days: int | None = None) -> int:
    """Delete InteractionHistory rows past retention. Returns rows deleted."""
    days = retention_days if retention_days is not None else get_settings().INTERACTION_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session_factory() as session:
        result = await session.execute(
            delete(InteractionHistory).where(InteractionHistory.timestamp < cutoff)
        )
        await session.commit()
        deleted = result.rowcount or 0

    logger.info("Purged %d interaction(s) older than %d days.", deleted, days)
    return deleted


if __name__ == "__main__":
    asyncio.run(purge_expired_interactions())
