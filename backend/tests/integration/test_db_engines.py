"""Engines and sessions (D-36), query counting and lazy loading (D-39), /health on the real database."""

import asyncio
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import QueryCanceled
from sqlalchemy import URL, Connection, Engine, insert, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session, selectinload

from app.core import db as core_db
from app.core.config import Settings, get_settings
from app.domain.models import POLine, PurchaseOrder
from app.main import create_app
from tests.integration import factories as f

CountQueries = Callable[[Engine | AsyncEngine], AbstractContextManager[list[str]]]


@pytest.fixture
def settings(migrated_url: URL) -> Settings:
    return Settings(database_url=migrated_url.render_as_string(hide_password=False))


@pytest.fixture
def app_db(migrated_url: URL, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the app's own cached settings and engines at the test database for one test."""
    monkeypatch.setenv("DATABASE_URL", migrated_url.render_as_string(hide_password=False))
    caches = (
        get_settings,
        core_db.get_async_engine,
        core_db.get_sync_engine,
        core_db.get_async_session_factory,
        core_db.get_sync_session_factory,
    )
    for cache in caches:
        cache.cache_clear()
    yield
    if core_db.get_sync_engine.cache_info().currsize:
        core_db.get_sync_engine().dispose()
    for cache in caches:
        cache.cache_clear()


# --- API pool -------------------------------------------------------------------------------------------------------


async def test_api_pool_serves_a_burst_of_concurrent_requests_within_its_limit(settings: Settings) -> None:
    engine = core_db.build_async_engine(settings, pool_size=2, max_overflow=1, pool_timeout=10)
    peak_checked_out = 0
    peak_server_connections = 0

    async def request(i: int) -> int:
        nonlocal peak_checked_out, peak_server_connections
        async with engine.connect() as conn:
            peak_checked_out = max(peak_checked_out, engine.pool.checkedout())
            server = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name = 'retailpilot-api' AND datname = current_database()"
                )
            )
            peak_server_connections = max(peak_server_connections, server.scalar_one())
            await conn.execute(text("SELECT pg_sleep(0.05)"))
            return (await conn.execute(text("SELECT :i"), {"i": i})).scalar_one()

    try:
        results = await asyncio.gather(*(request(i) for i in range(30)))
    finally:
        await engine.dispose()
    assert sorted(results) == list(range(30))  # every request served, none failed
    assert peak_checked_out == 3  # pool_size + max_overflow, never more
    assert peak_server_connections <= 3  # the database sees the same bound


async def test_exhausted_pool_fails_fast_instead_of_hanging(settings: Settings) -> None:
    engine = core_db.build_async_engine(settings, pool_size=1, max_overflow=0, pool_timeout=0.3)
    try:
        async with engine.connect():
            with pytest.raises(PoolTimeout):
                async with engine.connect():
                    pass
    finally:
        await engine.dispose()


async def test_api_engine_statement_timeout_is_5s_and_enforced(settings: Settings) -> None:
    engine = core_db.build_async_engine(settings)
    short = core_db.build_async_engine(settings.model_copy(update={"db_statement_timeout_ms": 200}))
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SHOW statement_timeout"))).scalar() == "5s"
        async with short.connect() as conn:
            with pytest.raises(DBAPIError) as raised:
                await conn.execute(text("SELECT pg_sleep(2)"))
            assert isinstance(raised.value.orig, QueryCanceled)
    finally:
        await engine.dispose()
        await short.dispose()


def test_worker_engine_has_its_own_pool_and_a_10_minute_timeout(settings: Settings) -> None:
    engine = core_db.build_sync_engine(settings)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SHOW statement_timeout")).scalar() == "10min"
            assert conn.execute(text("SHOW application_name")).scalar() == "retailpilot-worker"
        assert (engine.pool.size(), engine.pool._max_overflow) == (2, 3)  # type: ignore[attr-defined]
    finally:
        engine.dispose()


async def test_get_session_dependency_uses_the_async_api_engine(app_db: None) -> None:
    sessions = core_db.get_session()
    session = await anext(sessions)
    try:
        assert (await session.execute(text("SELECT current_database()"))).scalar() == "retailpilot_test"
        assert (await session.execute(text("SHOW application_name"))).scalar() == "retailpilot-api"
    finally:
        await sessions.aclose()
        await core_db.dispose_engines()


# --- query counting and lazy loading (D-39) -------------------------------------------------------------------------


def test_count_queries_counts_every_statement(engine: Engine, count_queries: CountQueries) -> None:
    with engine.connect() as conn, count_queries(engine) as statements:
        for i in range(3):
            conn.execute(text("SELECT :i"), {"i": i})
    assert len(statements) == 3


async def test_count_queries_works_on_the_async_engine(
    settings: Settings, count_queries: CountQueries
) -> None:
    engine = core_db.build_async_engine(settings)
    try:
        with count_queries(engine) as statements:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.execute(text("SELECT 2"))
        assert [s for s in statements if s.startswith("SELECT 1") or s.startswith("SELECT 2")] == [
            "SELECT 1",
            "SELECT 2",
        ]
    finally:
        await engine.dispose()


def _purchase_orders_with_lines(db: Connection, count: int, lines_each: int) -> list[uuid.UUID]:
    """`count` POs with `lines_each` lines each, inside the caller's transaction."""
    store, product, supplier = f.store(db), f.product(db), f.supplier(db)
    run = f.agent_run(db, run_date=None, agent_name="test")
    rec = f.recommendation(db, store, product, run_id=run)
    line = {
        "store_id": store,
        "product_id": product,
        "qty": 1,
        "unit_price": Decimal("10"),
        "source_rec_id": rec,
    }
    ids = []
    for _ in range(count):
        po = f.purchase_order(db, supplier, run)
        ids.append(po)
        db.execute(insert(POLine), [line | {"po_id": po} for _ in range(lines_each)])
    return ids


def test_selectinload_query_count_does_not_grow_with_rows(
    engine: Engine, count_queries: CountQueries
) -> None:
    """The Phase 6 per-endpoint pattern: same number of queries for 1 row and for N rows."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ids = _purchase_orders_with_lines(conn, count=8, lines_each=3)
            session = Session(bind=conn, join_transaction_mode="create_savepoint")

            def load(po_ids: list[uuid.UUID]) -> int:
                session.expunge_all()
                with count_queries(engine) as statements:
                    pos = session.scalars(
                        select(PurchaseOrder)
                        .where(PurchaseOrder.po_id.in_(po_ids))
                        .options(selectinload(PurchaseOrder.lines))
                    ).all()
                    assert sum(len(po.lines) for po in pos) == 3 * len(po_ids)
                return len(statements)

            assert load(ids[:1]) == load(ids) == 2  # one for the POs, one for all their lines
        finally:
            trans.rollback()


def test_relationships_raise_instead_of_lazy_loading(engine: Engine) -> None:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            [po_id] = _purchase_orders_with_lines(conn, count=1, lines_each=2)
            session = Session(bind=conn, join_transaction_mode="create_savepoint")
            po = session.get(PurchaseOrder, po_id)
            assert po is not None
            with pytest.raises(InvalidRequestError, match="lazy='raise'"):
                _ = po.lines
        finally:
            trans.rollback()


# --- /health ---------------------------------------------------------------------------------------------------------


def test_health_reports_ok_against_the_real_database(app_db: None) -> None:
    with TestClient(create_app()) as client:
        body = client.get("/health").json()
    assert body["checks"]["database"] == "ok"
