"""Test that the generated PlantUML ERD matches SQLAlchemy models and is not stale (Phase 2 LLD)."""

from app.domain.models import Base
from scripts.export_erd import DEFAULT_OUT, generate_puml


def test_erd_file_exists() -> None:
    assert DEFAULT_OUT.is_file(), (
        f"ERD file missing at {DEFAULT_OUT}; run `uv run python -m scripts.export_erd`"
    )


def test_erd_is_up_to_date_with_models() -> None:
    """Fails if a model/column changed without running `uv run python -m scripts.export_erd`."""
    current_content = DEFAULT_OUT.read_text(encoding="utf-8")
    expected_content = generate_puml()
    assert current_content == expected_content, (
        "ERD diagram is stale compared to SQLAlchemy models; run `uv run python -m scripts.export_erd`"
    )


def test_every_model_table_is_in_erd() -> None:
    content = DEFAULT_OUT.read_text(encoding="utf-8")
    for table_name in Base.metadata.tables:
        assert "class " in content and f'"{table_name}"' in content, f"Table {table_name} missing from ERD"
