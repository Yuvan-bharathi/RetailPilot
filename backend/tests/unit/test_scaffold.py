"""Phase 1 scaffold: settings, Celery app and OpenAPI wiring."""

import pytest

from app.core.config import Settings, get_settings
from app.main import create_app
from app.workers.celery_app import celery_app


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("JWT_SECRET", "s3cret")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm_model == "test-model"
        assert settings.jwt_secret.get_secret_value() == "s3cret"
    finally:
        get_settings.cache_clear()


def test_secrets_are_not_printed() -> None:
    settings = Settings(jwt_secret="top-secret")  # type: ignore[arg-type]

    assert "top-secret" not in repr(settings)


def test_celery_app_has_empty_beat_schedule_in_phase_1() -> None:
    assert celery_app.main == "retailpilot"
    assert celery_app.conf.beat_schedule == {}
    assert celery_app.conf.timezone == "Asia/Kolkata"


def test_openapi_documents_health_and_error_body() -> None:
    spec = create_app().openapi()

    assert "/health" in spec["paths"]
    assert "ErrorResponse" in spec["components"]["schemas"]
