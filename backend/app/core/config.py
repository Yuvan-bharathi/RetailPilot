"""Application settings, read from environment variables and the repo-root `.env` file.

Business parameters (thresholds, budgets, deadlines) do NOT live here: they are stored in the
BusinessRule table (docs/02-technical-spec.md §9). This module holds only infrastructure settings.
"""

import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path.cwd() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://retailpilot:retailpilot@localhost:5432/retailpilot"

    # API engine: async, pooled, short statement timeout (D-36, spec §11 connection budget)
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_s: float = 5.0
    db_pool_recycle_s: int = 1800
    db_statement_timeout_ms: int = 5_000
    # Celery / scripts engine: sync, small pool, long statement timeout (nightly run, MV refresh)
    worker_db_pool_size: int = 2
    worker_db_max_overflow: int = 3
    worker_db_statement_timeout_ms: int = 600_000

    # PoC users created by `python -m scripts.seed` (D-35); "demo" is accepted only when app_env == "local"
    seed_user_password: SecretStr | None = None
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # LLM explanations (D-44): Groq, OpenAI open-weight models. Numbers are never taken from the LLM — every
    # number in its text must appear in the evidence, else the deterministic template is used (rule 11).
    groq_api_key: SecretStr | None = None
    llm_provider: Literal["groq", "template"] = "groq"  # "template": never call an LLM
    llm_model: str = "openai/gpt-oss-120b"  # production model; best grounding for short factual text
    llm_fallback_model: str = "openai/gpt-oss-20b"  # production model; used on errors / rate limits
    llm_reasoning_effort: Literal["low", "medium", "high"] = "low"
    llm_temperature: float = 0.0  # spec Phase 5: temperature 0
    llm_max_completion_tokens: int = 4096  # reasoning tokens count toward this limit
    llm_timeout_s: float = 30.0
    llm_batch_size: int = 20

    app_timezone: str = "Asia/Kolkata"
    cors_origins: list[str] = ["http://localhost:5173"]

    health_check_timeout_s: float = 2.0


MIN_JWT_SECRET_BYTES = 32


def check_secrets(settings: Settings) -> Settings:
    """Outside local/test, refuse the default or a short JWT secret (HS256 needs ≥ 32 bytes, RFC 7518 §3.2)."""
    secret = settings.jwt_secret.get_secret_value()
    if settings.app_env not in ("local", "test") and (
        secret == "change-me" or len(secret.encode()) < MIN_JWT_SECRET_BYTES
    ):
        raise ValueError(
            f"JWT_SECRET must be set to at least {MIN_JWT_SECRET_BYTES} random bytes in {settings.app_env}"
        )
    return settings


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (call `get_settings.cache_clear()` in tests after changing env)."""
    return check_secrets(Settings())
