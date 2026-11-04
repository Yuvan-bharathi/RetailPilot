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


def test_celery_beat_schedule_matches_spec_section_7() -> None:
    """Phase 5 jobs (spec §7, D-35): nightly run 23:30 IST, deadlines every 15 min, partition maintenance."""
    assert celery_app.main == "retailpilot"
    assert celery_app.conf.timezone == "Asia/Kolkata"
    schedule = celery_app.conf.beat_schedule
    assert {name: job["task"] for name, job in schedule.items()} == {
        "nightly-run": "nightly_run_task",
        "approval-deadlines": "approval_deadline_task",
        "partition-maintenance": "partition_maintenance_task",
    }
    nightly = schedule["nightly-run"]["schedule"]
    assert (nightly.hour, nightly.minute) == ({23}, {30})
    assert schedule["approval-deadlines"]["schedule"] == 900.0


def test_openapi_documents_health_and_error_body() -> None:
    spec = create_app().openapi()

    assert "/health" in spec["paths"]
    assert "ErrorResponse" in spec["components"]["schemas"]


def test_weak_jwt_secret_is_refused_outside_local() -> None:
    import pytest

    from app.core.config import check_secrets

    assert check_secrets(Settings(app_env="local", jwt_secret="change-me"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="JWT_SECRET"):
        check_secrets(Settings(app_env="production", jwt_secret="change-me"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="JWT_SECRET"):
        check_secrets(Settings(app_env="staging", jwt_secret="short"))  # type: ignore[arg-type]
    assert check_secrets(Settings(app_env="production", jwt_secret="y" * 40))  # type: ignore[arg-type]
