"""
Application configuration loaded from environment variables.

Uses pydantic-settings for validation and type coercion. All settings
are read from a .env file at the project root or from the environment.

Version: 2026-02-12
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    # -- Observability -------------------------------------------------------
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_PROJECT: str = "intelligent-tutor"

    # -- Databases -----------------------------------------------------------
    POSTGRES_URL: str = "postgresql+asyncpg://tutor:tutor_pass@localhost:5432/tutor_db"
    POSTGRES_URL_SYNC: str = "postgresql://tutor:tutor_pass@localhost:5432/tutor_db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # -- Code Execution ------------------------------------------------------
    CODE_EXEC_TIMEOUT: int = 5  # seconds
    CODE_EXEC_MAX_MEMORY_MB: int = 256

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
