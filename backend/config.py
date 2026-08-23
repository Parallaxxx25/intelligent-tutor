"""
Application configuration loaded from environment variables.

Uses pydantic-settings for validation and type coercion. All settings
are read from a .env file at the project root or from the environment.

Version: 2026-02-12
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os
from dotenv import load_dotenv

# Force environment variables into the OS environ where LangSmith can see them globally
load_dotenv()

from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Resolve the project root (one level above backend/)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Centralised application settings."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- LLM -----------------------------------------------------------------
    GOOGLE_API_KEY: str = ""
    LLM_MODEL: str = "gemini/gemini-2.5-flash"
    OPENROUTER_API_KEY: str = ""
    # 0 disables dynamic thinking — ~3x latency cut, ~40% fewer output
    # tokens, at the cost of some reasoning depth. Re-run the eval suite
    # (backend/evaluation/) before changing this away from 0 for a lab.
    THINKING_BUDGET: int = 0
    GEMINI_CALL_TIMEOUT: int = 15  # seconds, per Gemini call
    # Kill switch — flips the LLM pipeline to the deterministic pipeline
    # without a redeploy. Flip this, not GOOGLE_API_KEY, to disable Gemini.
    LLM_ENABLED: bool = True
    # Dedicated thread pool for /api/v1/hint's Gemini calls (backend/llm_executor.py)
    # — kept separate from anyio's shared default pool so a Gemini stall
    # can't park /grade's threads too.
    LLM_EXECUTOR_MAX_WORKERS: int = 12
    LLM_SEMAPHORE_LIMIT: int = 6

    # -- Observability -------------------------------------------------------
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_TRACING: bool = True
    LANGCHAIN_PROJECT: str = "intelligent-tutor"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    # -- Databases -----------------------------------------------------------
    POSTGRES_URL: str = "postgresql+asyncpg://tutor:tutor_pass@localhost:5432/tutor_db"
    POSTGRES_URL_SYNC: str = "postgresql://tutor:tutor_pass@localhost:5432/tutor_db"
    # Read-only role for student query execution (code_executor.py). Empty
    # falls back to POSTGRES_URL_SYNC — set this once the student_ro role
    # exists so a submitted query physically cannot read app tables.
    POSTGRES_URL_EXEC: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"

    # -- Code Execution ------------------------------------------------------
    CODE_EXEC_TIMEOUT: int = 5  # seconds
    CODE_EXEC_MAX_MEMORY_MB: int = 256

    # -- RAG (Phase 2) -------------------------------------------------------
    # Persistent by default — an empty string reverts to in-memory (ephemeral,
    # wipes RAG docs + long-term memory on every restart). Set "" explicitly
    # in tests that need a clean, throwaway store.
    CHROMA_PERSIST_DIR: str = "./.chroma"
    EMBEDDING_MODEL: str = "models/gemini-embedding-001"

    # -- Slide-material RAG ---------------------------------------------------
    SLIDE_MATERIAL_DIR: str = "slide-material"
    CHROMA_SLIDE_COLLECTION: str = "slide_material"
    LOCAL_EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    USE_LOCAL_EMBEDDINGS: bool = True
    SLIDE_RAG_ENABLED: bool = True
    SLIDE_RAG_N_RESULTS: int = 2

    # -- Persistence & State (Phase 3) ----------------------------------------
    REDIS_SESSION_TTL: int = 86400  # 24 hours in seconds

    # -- Guardrails (Phase 2) ------------------------------------------------
    GUARDRAIL_MAX_QUERY_LENGTH: int = 5000
    GUARDRAIL_MAX_RESPONSE_LENGTH: int = 3000
    DEFAULT_PIPELINE_MODE: str = "deterministic"  # "deterministic" or "llm"

    # -- Security --------------------------------------------------------------
    # Empty = auth disabled (local dev). Set to require the X-API-Key header
    # on /api/submit and /api/debug/* and to enable /api/users/{id}/data deletion.
    API_KEY: str = ""
    # Server-to-server key for /api/v1/* (an integrating platform's backend
    # calling this service). Deliberately separate from API_KEY — a
    # different caller, a different trust boundary, rotated independently.
    SERVICE_KEY: str = ""
    INTERACTION_RETENTION_DAYS: int = 180

    # -- Application ---------------------------------------------------------
    ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton)."""
    return Settings()
