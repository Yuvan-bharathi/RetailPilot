"""Model metadata rules (spec §10, D-35 … D-40), checked without a database."""

import asyncio
import importlib.util
import re
import typing
from enum import StrEnum
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric
from sqlalchemy.orm import configure_mappers

from app.core.config import Settings
from app.core.db import selector_event_loop
from app.domain.models import Base
from app.domain.models import enums as e
from app.domain.schemas import common, dtos
from data.synthetic.generate import BUSINESS_RULES
from scripts.seed import DEMO_PASSWORD, seed_password

BACKEND = Path(__file__).resolve().parents[2]
SPEC = BACKEND.parent / "docs" / "02-technical-spec.md"
TABLES = Base.metadata.tables


def _migration(name: str) -> ModuleType:
    path = BACKEND / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tables_match_the_spec_table_list() -> None:
    text = SPEC.read_text(encoding="utf-8")
    block = text[text.index("- Tables (CD-1, CD-2):") :].split("\n\n")[0]
    names = {n.replace("(ext)", "").strip(" .\n") for n in block.split(":", 1)[1].split(",")}
    assert set(TABLES) == names


def test_every_table_has_created_and_updated_timestamps() -> None:
    for table in TABLES.values():
        assert {"created_at", "updated_at"} <= set(table.c.keys()), table.name
        assert table.c.created_at.type.timezone, table.name  # type: ignore[attr-defined]


def test_every_foreign_key_is_indexed() -> None:
    """A FK is covered when an index or the primary key starts with its columns (spec §10: all FKs indexed)."""
    missing = []
    for table in TABLES.values():
        prefixes = [[c.name for c in table.primary_key.columns]]
        prefixes += [[getattr(c, "name", str(c)) for c in ix.expressions] for ix in table.indexes]
        for fk in table.constraints:
            if isinstance(fk, ForeignKeyConstraint):
                cols = [c.name for c in fk.columns]
                if not any(p[: len(cols)] == cols for p in prefixes):
                    missing.append(f"{table.name}({', '.join(cols)})")
    assert missing == []


def test_money_columns_are_numeric_14_2() -> None:
    money = {
        ("product", "cost_price"),
        ("product", "selling_price"),
        ("sales_line", "unit_price"),
        ("sales_line", "discount"),
        ("recommendation", "lost_sales_value"),
        ("recommendation", "lost_profit"),
        ("purchase_order", "total_value"),
        ("po_line", "unit_price"),
        ("transfer_order", "transfer_cost"),
        ("transfer_order", "loss_value"),
        ("transfer_route", "fixed_cost"),
        ("lost_sales_estimate", "lost_revenue"),
        ("supplier_store_terms", "delivery_charge"),
    }
    for table, column in money:
        col_type = TABLES[table].c[column].type
        assert isinstance(col_type, Numeric) and (col_type.precision, col_type.scale) == (14, 2), (
            table,
            column,
        )


def test_partitioned_tables_carry_the_partition_key_in_their_primary_key() -> None:
    assert TABLES["sales_line"].dialect_options["postgresql"]["partition_by"] == "RANGE (txn_date)"
    assert TABLES["inventory_movement"].dialect_options["postgresql"]["partition_by"] == "RANGE (occurred_at)"
    assert [c.name for c in TABLES["sales_line"].primary_key] == ["bill_id", "line_no", "txn_date"]
    assert [c.name for c in TABLES["inventory_movement"].primary_key] == ["movement_id", "occurred_at"]


def test_every_relationship_refuses_lazy_loading() -> None:
    """D-39: related rows are loaded explicitly (selectinload / joinedload), never by an implicit lazy load."""
    configure_mappers()
    relationships = [r for m in Base.registry.mappers for r in m.relationships]
    assert relationships  # the rule is exercised
    assert {r.key: r.lazy for r in relationships if r.lazy != "raise"} == {}


@pytest.mark.parametrize(
    ("literal", "enum"),
    [
        (dtos.RecType, e.RecType),
        (dtos.RecStatus, e.RecStatus),
        (dtos.MovementType, e.MovementType),
        (dtos.TransferStatus, e.TransferStatus),
        (dtos.POStatus, e.POStatus),
        (dtos.LineStatus, e.LineStatus),
        (common.Role, e.Role),
        (common.Priority, e.Priority),
    ],
)
def test_api_literals_and_database_enums_list_the_same_values(literal: object, enum: type[StrEnum]) -> None:
    assert set(typing.get_args(literal)) == {v.value for v in enum}


def test_status_check_constraints_list_every_enum_value() -> None:
    checks = {
        str(c.name): str(c.sqltext)
        for c in TABLES["recommendation"].constraints
        if isinstance(c, CheckConstraint)
    }
    status = next(sql for name, sql in checks.items() if name.endswith("status"))
    assert all(f"'{v.value}'" in status for v in e.RecStatus)


def test_business_rule_migration_seeds_the_tested_defaults() -> None:
    assert _migration("0002_business_rules").DEFAULT_RULES == BUSINESS_RULES


def test_initial_migration_partitions_two_years_of_months() -> None:
    months = _migration("0001_schema").PARTITION_MONTHS
    assert (months[0], months[-1], len(months)) == ((2026, 1), (2027, 12), 24)


def test_seed_password_demo_only_in_local() -> None:
    assert seed_password(Settings(app_env="local", seed_user_password=None)) == DEMO_PASSWORD
    assert seed_password(Settings(app_env="staging", seed_user_password=SecretStr("s3cret!"))) == "s3cret!"
    with pytest.raises(SystemExit, match="SEED_USER_PASSWORD"):
        seed_password(Settings(app_env="production", seed_user_password=None))


def test_engine_settings_defaults_follow_the_connection_budget() -> None:
    s = Settings()
    assert (s.db_pool_size, s.db_max_overflow, s.db_statement_timeout_ms) == (10, 10, 5_000)
    assert (s.worker_db_pool_size, s.worker_db_max_overflow) == (2, 3)
    assert s.worker_db_statement_timeout_ms == 600_000
    # spec §11 example: 2 API workers + 4 Celery processes + 10 headroom stays below max_connections = 100
    assert (
        2 * (s.db_pool_size + s.db_max_overflow) + 4 * (s.worker_db_pool_size + s.worker_db_max_overflow) + 10
        < 100
    )


def test_uvicorn_loop_option_gives_a_selector_loop() -> None:
    loop = selector_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_large_responses_are_gzipped(client: TestClient) -> None:
    response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    small = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers  # below minimum_size=1000


def test_index_names_fit_postgresql_limit() -> None:
    names = [ix.name for t in TABLES.values() for ix in t.indexes if ix.name]
    assert all(len(n) <= 63 and re.fullmatch(r"[a-z0-9_]+", n) for n in names)
