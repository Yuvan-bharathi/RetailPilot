"""Dependency checks for GET /health. Checks never raise: a down dependency is reported, not fatal."""

from typing import Literal

import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.logging import get_logger

logger = get_logger(__name__)

CheckStatus = Literal["ok", "unavailable"]


async def check_database(url: str, timeout_s: float) -> CheckStatus:
    """Async psycopg check (D-36) on its own unpooled connection, so a full API pool cannot fail the probe."""
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"connect_timeout": max(1, int(timeout_s))}
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # any driver/network error means "unavailable"
        logger.warning("database health check failed: %s", type(exc).__name__)
        return "unavailable"
    finally:
        await engine.dispose()


def check_redis(url: str, timeout_s: float) -> CheckStatus:
    client = redis.Redis.from_url(url, socket_connect_timeout=timeout_s, socket_timeout=timeout_s)
    try:
        client.ping()
        return "ok"
    except Exception as exc:
        logger.warning("redis health check failed: %s", type(exc).__name__)
        return "unavailable"
    finally:
        client.close()
