"""Migrations on a real PostgreSQL 16: clean upgrade/downgrade, every object exists, indexes, partitions, drift."""

from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.pool import NullPool

from alembic import command
from app.domain.models import MATERIALIZED_VIEWS, PARTITIONED_TABLES, Base
from app.domain.models.schema_objects import make_include_object
from tests.integration.conftest import alembic_config, drop_database, recreate_database

MONTHS = [f"{y}_{m:02d}" for y in (2026, 2027) for m in range(1, 13)]

#: Indexes that exist for a specific query pattern (D-38) — name → fragment its definition must contain.
QUERY_INDEXES = {
    "ix_recommendation_inbox_pending": "(store_id, priority_rank, created_at) WHERE (status = 'PENDING'::text)",
    "ix_po_line_store_pending": "(store_id, po_id) WHERE (line_status = 'PENDING'::text)",
    "ix_purchase_order_l1_deadline_pending": "(l1_deadline) WHERE (status = 'PENDING_L1'::text)",
    "ix_transfer_order_from_active": "(from_store_id) WHERE (status = ANY",
    "ix_transfer_order_to_active": "(to_store_id) WHERE (status = ANY",
    "ix_batch_store_expiry_held": "(store_id, expiry_date) WHERE (qty > 0)",
    "ix_notification_user_unread": "(user_id, created_at) WHERE (read_at IS NULL)",
    "ix_product_name_trgm": "USING gin (name gin_trgm_ops)",
    "ix_product_sku_trgm": "USING gin (sku gin_trgm_ops)",
    "ix_inventory_movement_store_time": "(store_id, occurred_at DESC, movement_id DESC)",
    "ix_inventory_movement_store_product_time": "(store_id, product_id, occurred_at DESC)",
    "ix_sales_line_store_product_day": "(store_id, product_id, txn_date)",
    "uq_business_rule_key_scope": "(rule_key, scope_store_id) NULLS NOT DISTINCT",
    "uq_agent_run_nightly_run_date": "(run_date) WHERE ((agent_name = 'nightly'::text) AND (status = ANY",
}


def _relations(conn: Connection) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'm', 'v')"
        )
    )
    return {r[0] for r in rows}


@pytest.fixture
def scratch_db(admin_engine: Engine) -> Iterator[Engine]:
    """An empty database of its own, so upgrade/downgrade do not disturb the session's test database."""
    name = "retailpilot_test_migrations"
    url = recreate_database(admin_engine, name)
    engine = create_engine(url, poolclass=NullPool)
    yield engine
    engine.dispose()
    drop_database(admin_engine, name)


def test_upgrade_head_and_downgrade_base_on_a_clean_database(scratch_db: Engine) -> None:
    config = alembic_config(scratch_db.url)

    command.upgrade(config, "head")
    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
        after_upgrade = _relations(conn)
        assert set(Base.metadata.tables) | set(MATERIALIZED_VIEWS) <= after_upgrade
        assert conn.execute(text("SELECT count(*) FROM business_rule")).scalar() == 16

    command.downgrade(config, "base")
    with scratch_db.connect() as conn:
        assert _relations(conn) == {"alembic_version"}  # tables, partitions and views all gone
        assert conn.execute(text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'")).scalar() == 0

    command.upgrade(config, "head")  # and the round trip works again
    with scratch_db.connect() as conn:
        assert _relations(conn) == after_upgrade


def test_every_table_partition_and_view_exists(db: Connection) -> None:
    relations = _relations(db)
    assert set(Base.metadata.tables) <= relations
    for table in PARTITIONED_TABLES:
        expected = {f"{table}_{m}" for m in MONTHS} | {f"{table}_default"}
        partitions = db.execute(
            text("SELECT inhrelid::regclass::text FROM pg_inherits WHERE inhparent = CAST(:t AS regclass)"),
            {"t": table},
        )
        assert {r[0] for r in partitions} == expected, table
    views = db.execute(text("SELECT matviewname FROM pg_matviews WHERE schemaname = 'public'"))
    assert {r[0] for r in views} == set(MATERIALIZED_VIEWS)


def test_query_pattern_indexes_exist_with_their_predicates(db: Connection) -> None:
    rows = db.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"))
    defs = {name: definition for name, definition in rows}
    problems = {
        name: defs.get(name) for name, fragment in QUERY_INDEXES.items() if fragment not in defs.get(name, "")
    }
    assert problems == {}


def test_partitions_carry_every_parent_index(db: Connection) -> None:
    for table in PARTITIONED_TABLES:
        parent = db.execute(
            text("SELECT count(*) FROM pg_index WHERE indrelid = CAST(:t AS regclass)"), {"t": table}
        ).scalar()
        per_partition = db.execute(
            text(
                "SELECT i.inhrelid::regclass::text, (SELECT count(*) FROM pg_index x WHERE x.indrelid = i.inhrelid) "
                "FROM pg_inherits i WHERE i.inhparent = CAST(:t AS regclass)"
            ),
            {"t": table},
        )
        assert {name: n for name, n in per_partition if n != parent} == {}, table


def _attached_parent_indexes(conn: Connection, partition: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT parent.relname FROM pg_index x "
            "JOIN pg_inherits inh ON inh.inhrelid = x.indexrelid "
            "JOIN pg_class parent ON parent.oid = inh.inhparent "
            "WHERE x.indrelid = CAST(:p AS regclass)"
        ),
        {"p": partition},
    )
    return {r[0] for r in rows}


def _parent_indexes(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(
        text("SELECT indexrelid::regclass::text FROM pg_index WHERE indrelid = CAST(:t AS regclass)"),
        {"t": table},
    )
    return {r[0] for r in rows}


def test_a_newly_created_partition_inherits_the_parent_indexes(db: Connection) -> None:
    """D-38: the Phase 5 partition job only has to CREATE TABLE … PARTITION OF; indexes come with it."""
    db.execute(
        text(
            "CREATE TABLE inventory_movement_2028_01 PARTITION OF inventory_movement "
            "FOR VALUES FROM ('2028-01-01 00:00:00+00') TO ('2028-02-01 00:00:00+00')"
        )
    )
    db.execute(
        text(
            "CREATE TABLE sales_line_2028_01 PARTITION OF sales_line "
            "FOR VALUES FROM ('2028-01-01') TO ('2028-02-01')"
        )
    )
    for table in PARTITIONED_TABLES:
        expected = _parent_indexes(db, table)
        assert len(expected) >= 3
        assert _attached_parent_indexes(db, f"{table}_2028_01") == expected
    # (rolled back with the test transaction)


def test_models_and_migrated_database_do_not_drift(engine: Engine) -> None:
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "include_object": make_include_object(Base.metadata)}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_reflected_tables_have_their_primary_keys(engine: Engine) -> None:
    inspector = inspect(engine)
    for name, table in Base.metadata.tables.items():
        reflected = inspector.get_pk_constraint(name)["constrained_columns"]
        assert reflected == [c.name for c in table.primary_key], name
