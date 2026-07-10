"""
Settings — single source of truth for runtime configuration.

Reads from environment variables and a `.env` file in the repo root.
Pydantic validates everything at startup, so a misconfigured deploy
fails loud, not silently.

Spec: docs/classes/Settings.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["mock", "openai", "anthropic"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration loaded once at process start."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---------------------------------------------------------------
    llm_provider: ProviderName = Field(default="mock", description="Active LLM provider key.")
    llm_model: str = Field(default="gpt-4o-mini", description="Model name passed to the provider.")
    openai_api_key: str = Field(default="", description="Required when llm_provider='openai'.")
    anthropic_api_key: str = Field(default="", description="Required when llm_provider='anthropic'.")

    # --- HTTP --------------------------------------------------------------
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed origins.",
    )

    # --- Logging -----------------------------------------------------------
    log_level: LogLevel = Field(default="INFO")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Lazy + cached so tests can override env vars before first call.
    """
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Settings()
    return _SINGLETON


_SINGLETON: Settings | None = None
