"""Application settings, read from environment variables and the repo-root `.env` file.

Business parameters (thresholds, budgets, deadlines) do NOT live here: they are stored in the
BusinessRule table (docs/02-technical-spec.md §9). This module holds only infrastructure settings.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the repository root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path.cwd() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://retailpilot:retailpilot@localhost:5432/retailpilot"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5-5"

    app_timezone: str = "Asia/Kolkata"
    cors_origins: list[str] = ["http://localhost:5173"]

    health_check_timeout_s: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (call `get_settings.cache_clear()` in tests after changing env)."""
    return Settings()
