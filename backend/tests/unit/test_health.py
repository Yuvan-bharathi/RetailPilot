import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.core import health
from app.main import create_app


def test_health_ok_when_dependencies_up(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_health_degraded_but_200_when_dependencies_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "check_database", lambda url, timeout_s: "unavailable")
    monkeypatch.setattr(health, "check_redis", lambda url, timeout_s: "ok")

    with TestClient(create_app()) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "unavailable", "redis": "ok"}


def test_real_checks_report_unavailable_for_unreachable_hosts() -> None:
    # Port 1 on localhost refuses connections immediately: no network wait, no exception escapes.
    assert health.check_database("postgresql+psycopg://u:p@127.0.0.1:1/db", timeout_s=1) == "unavailable"
    assert health.check_redis("redis://127.0.0.1:1/0", timeout_s=1) == "unavailable"
