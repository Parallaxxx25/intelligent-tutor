"""
FastAPI application entry point for the Intelligent Tutoring System.

Run with:
    uvicorn backend.main:app --reload

Version: 2026-02-12
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as api_router
from backend.api.websocket import router as ws_router
from backend.config import get_settings
from backend.db.database import close_db, init_db
from backend.memory.redis_session import get_session_manager
from backend.memory.long_term import get_long_term_memory

settings = get_settings()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup / shutdown lifecycle."""
    logger.info("Starting Intelligent Tutoring System...")
    await init_db()
    logger.info("Database initialised.")

    # Initialize RAG knowledge base (Phase 2)
    try:
        from backend.rag.retriever import initialize_knowledge_base
        initialize_knowledge_base()
        logger.info("RAG knowledge base initialised.")
    except Exception as e:
        logger.warning("RAG init failed (non-fatal): %s", e)

    # Initialize memory components (Phase 3)
    try:
        session_manager = get_session_manager()
        await session_manager.connect()
        
        long_term_memory = get_long_term_memory()
        long_term_memory.initialize()
        logger.info("Memory components initialised (Redis + Long-term).")
    except Exception as e:
        logger.warning("Memory init failed (non-fatal): %s", e)

    yield
    # Shutdown memory components (Phase 3)
    try:
        session_manager = get_session_manager()
        await session_manager.disconnect()
    except Exception as e:
        logger.warning("Memory disconnect failed (non-fatal): %s", e)

    await close_db()
    logger.info("Application shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Intelligent Tutoring System",
    description=(
        "Multi-agent AI tutoring system with automated grading, "
        "error diagnosis, and adaptive pedagogical hints."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(api_router)
app.include_router(ws_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint — redirect to docs."""
    return {
        "message": "Intelligent Tutoring System API",
        "docs": "/docs",
    }
