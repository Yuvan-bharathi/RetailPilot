"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import health
from app.core.db import use_selector_event_loop
from app.main import create_app

use_selector_event_loop()  # psycopg async cannot use Windows' Proactor loop (D-36); runs before any loop exists


def _async_status(status: str):  # type: ignore[no-untyped-def]
    async def check(url: str, timeout_s: float) -> str:
        return status

    return check


@pytest.fixture
def deps_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend PostgreSQL and Redis are reachable (unit tests never touch the network)."""
    monkeypatch.setattr(health, "check_database", _async_status("ok"))
    monkeypatch.setattr(health, "check_redis", lambda url, timeout_s: "ok")


@pytest.fixture
def client(deps_ok: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests never call a live model (docs/08 §7): explanations use templates, LLM agents their recorded or
    deterministic paths. A test that needs a model injects a scripted one."""
    from app.core.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "template")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
