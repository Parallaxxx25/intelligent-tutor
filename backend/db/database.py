"""
Async database engine and session management.

Provides:
  - SQLAlchemy async engine (asyncpg driver)
  - Async session factory
  - FastAPI dependency ``get_db()`` for request-scoped sessions
  - ``init_db()`` to create all tables on startup

Version: 2026-02-12
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings
from backend.db.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine & session factory (initialised lazily via ``init_db``)
# ---------------------------------------------------------------------------

_settings = get_settings()

engine = create_async_engine(
    _settings.POSTGRES_URL,
    echo=_settings.DEBUG,
    pool_size=5,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async session, rolled back on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create all tables (idempotent). Call once at application startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified.")


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    await engine.dispose()
    logger.info("Database engine disposed.")
