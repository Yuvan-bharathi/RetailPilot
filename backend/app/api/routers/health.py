"""GET /health — liveness plus dependency status. Always 200 while the API process is up."""

from typing import Literal

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import __version__
from app.core import health
from app.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthChecks(BaseModel):
    database: health.CheckStatus
    redis: health.CheckStatus


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: HealthChecks


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    settings = get_settings()
    timeout = settings.health_check_timeout_s
    database = await run_in_threadpool(health.check_database, settings.database_url, timeout)
    cache = await run_in_threadpool(health.check_redis, settings.redis_url, timeout)
    overall: Literal["ok", "degraded"] = "ok" if database == "ok" and cache == "ok" else "degraded"
    return HealthResponse(
        status=overall, version=__version__, checks=HealthChecks(database=database, redis=cache)
    )
