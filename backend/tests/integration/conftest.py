"""PostgreSQL fixtures for integration tests.

The session creates a fresh `retailpilot_test` database next to the one in DATABASE_URL, migrates it to head and
drops it at the end. Tests that change data use `db` (a connection inside a transaction that is rolled back), so
they do not see each other's rows. When PostgreSQL is not reachable every test here is skipped with the reason.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import URL, Connection, Engine, create_engine, event, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import get_settings

BACKEND = Path(__file__).resolve().parents[2]
TEST_DB = "retailpilot_test"

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


def database_url(name: str) -> URL:
    return make_url(get_settings().database_url).set(database=name)


def alembic_config(url: URL) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """AUTOCOMMIT engine on the main database, used to create and drop test databases."""
    url = make_url(get_settings().database_url)
    engine = create_engine(
        url, isolation_level="AUTOCOMMIT", poolclass=NullPool, connect_args={"connect_timeout": 3}
    )
    try:
        engine.connect().close()
    except OperationalError as exc:
        pytest.skip(
            f"PostgreSQL not reachable at {url.host}:{url.port} ({type(exc).__name__}); "
            "start it with `docker compose --env-file .env -f infra/docker-compose.yml up -d`"
        )
    yield engine
    engine.dispose()


def recreate_database(admin: Engine, name: str) -> URL:
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    return database_url(name)


def drop_database(admin: Engine, name: str) -> None:
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def migrated_url(admin_engine: Engine) -> Iterator[URL]:
    """`retailpilot_test`, freshly created and upgraded to head for this test session."""
    url = recreate_database(admin_engine, TEST_DB)
    command.upgrade(alembic_config(url), "head")
    yield url
    drop_database(admin_engine, TEST_DB)


@pytest.fixture(scope="session")
def engine(migrated_url: URL) -> Iterator[Engine]:
    eng = create_engine(migrated_url, poolclass=NullPool)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is always rolled back."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


@contextmanager
def _count_queries(target: Engine | AsyncEngine) -> Iterator[list[str]]:
    sync = target.sync_engine if isinstance(target, AsyncEngine) else target
    statements: list[str] = []

    def before(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        # savepoints are transaction plumbing (nested sessions in tests), not data queries
        if (
            not statement.lstrip()
            .upper()
            .startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT"))
        ):
            statements.append(statement)

    event.listen(sync, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(sync, "before_cursor_execute", before)


@pytest.fixture
def count_queries() -> Callable[[Engine | AsyncEngine], AbstractContextManager[list[str]]]:
    """`with count_queries(engine) as statements: …` — every SQL statement the engine sent, savepoints excluded
    (D-39).

    Phase 6 uses it per list endpoint: the count for 1 row and for N rows must be equal.
    """
    return _count_queries
