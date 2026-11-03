"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import health
from app.main import create_app


@pytest.fixture
def deps_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend PostgreSQL and Redis are reachable (unit tests never touch the network)."""
    monkeypatch.setattr(health, "check_database", lambda url, timeout_s: "ok")
    monkeypatch.setattr(health, "check_redis", lambda url, timeout_s: "ok")


@pytest.fixture
def client(deps_ok: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
