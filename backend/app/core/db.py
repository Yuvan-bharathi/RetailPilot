"""Database engines and sessions (D-36, spec §11).

Two engines with separate pools:
- **API** — async SQLAlchemy over psycopg 3 (`create_async_engine("postgresql+psycopg://…")` selects the async
  driver). Pooled, `pool_pre_ping`, and a server-side `statement_timeout` of `db_statement_timeout_ms` (5 s).
- **Worker** — sync engine for Celery tasks, Alembic-adjacent scripts and seeding, with its own small pool and a
  long `statement_timeout` (`worker_db_statement_timeout_ms`, 10 min) so the nightly run and the materialized-view
  refresh are not cut off.

Connection budget: api_workers × (pool_size + max_overflow) + celery_processes × (worker pool + overflow) +
headroom must stay below PostgreSQL `max_connections` (spec §11).

Windows: psycopg's async mode cannot run on the Proactor event loop, which uvicorn and asyncio pick by default.
Run the API with `--loop app.core.db:selector_event_loop`; tests call `use_selector_event_loop()` before any
loop exists. Linux is unaffected.
"""

import asyncio
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def use_selector_event_loop() -> None:
    """psycopg async needs a selector event loop; Windows defaults to Proactor. No-op elsewhere."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pragma: no cover


def selector_event_loop() -> asyncio.AbstractEventLoop:
    """uvicorn `--loop app.core.db:selector_event_loop` (uvicorn calls a custom loop value with no arguments):
    a selector loop on every platform, which psycopg async needs on Windows."""
    return asyncio.SelectorEventLoop()


def _connect_args(statement_timeout_ms: int, application_name: str) -> dict[str, Any]:
    # libpq `options`: applied by the server to every connection of the pool, before any query.
    return {
        "options": f"-c statement_timeout={statement_timeout_ms}",
        "application_name": application_name,
    }


def build_async_engine(settings: Settings, **overrides: Any) -> AsyncEngine:
    kwargs: dict[str, Any] = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_s,
        "pool_recycle": settings.db_pool_recycle_s,
        "pool_pre_ping": True,
        "connect_args": _connect_args(settings.db_statement_timeout_ms, "retailpilot-api"),
    }
    kwargs.update(overrides)
    return create_async_engine(settings.database_url, **kwargs)


def build_sync_engine(settings: Settings, **overrides: Any) -> Engine:
    kwargs: dict[str, Any] = {
        "pool_size": settings.worker_db_pool_size,
        "max_overflow": settings.worker_db_max_overflow,
        "pool_recycle": settings.db_pool_recycle_s,
        "pool_pre_ping": True,
        "connect_args": _connect_args(settings.worker_db_statement_timeout_ms, "retailpilot-worker"),
    }
    kwargs.update(overrides)
    return create_engine(settings.database_url, **kwargs)


@lru_cache
def get_async_engine() -> AsyncEngine:
    return build_async_engine(get_settings())


@lru_cache
def get_sync_engine() -> Engine:
    return build_sync_engine(get_settings())


@lru_cache
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


@lru_cache
def get_sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one async session per request, rolled back if the handler raises."""
    async with get_async_session_factory()() as session:
        yield session


@contextmanager
def worker_session() -> Iterator[Session]:
    """Sync session for Celery tasks and scripts: commits on success, rolls back on error."""
    with get_sync_session_factory()() as session, session.begin():
        yield session


async def dispose_engines() -> None:
    """Close pooled connections (application shutdown)."""
    if get_async_engine.cache_info().currsize:
        await get_async_engine().dispose()
    if get_sync_engine.cache_info().currsize:
        get_sync_engine().dispose()
