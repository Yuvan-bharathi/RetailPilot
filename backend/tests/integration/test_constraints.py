"""Constraints, partition routing, generated columns, materialized views and seeding on PostgreSQL 16."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Connection, Engine, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.domain.models import (
    AgentRun,
    AppUser,
    BusinessRule,
    InventoryDailySnapshot,
    InventoryMovement,
    POLine,
    Recommendation,
    SalesLine,
    SalesTransaction,
    Store,
    StoreProduct,
    TransferOrder,
)
from data.synthetic.catalog import STORES
from scripts.seed import seed
from tests.integration import factories as f

D = date(2026, 11, 3)


def _rejected(conn: Connection, statement: object) -> bool:
    """True if PostgreSQL rejects the statement with an integrity error (checked in a savepoint)."""
    try:
        with conn.begin_nested():
            conn.execute(statement)  # type: ignore[call-overload]
    except IntegrityError:
        return True
    return False


# --- check constraints and keys ---------------------------------------------------------------------------------


def test_status_checks_reject_unknown_values(db: Connection) -> None:
    store, product = f.store(db), f.product(db)
    rec = f.recommendation(db, store, product)
    assert _rejected(db, update(Recommendation).where(Recommendation.rec_id == rec).values(status="BOGUS"))
    assert _rejected(db, update(Recommendation).where(Recommendation.rec_id == rec).values(rec_type="BOGUS"))
    assert not _rejected(
        db, update(Recommendation).where(Recommendation.rec_id == rec).values(status="SUPERSEDED")
    )
    run = f.agent_run(db, run_date=None, agent_name="x")
    assert _rejected(db, update(AgentRun).where(AgentRun.run_id == run).values(status="DONE"))


def test_composite_primary_keys_block_duplicates(db: Connection) -> None:
    store, product = f.store(db), f.product(db)
    row = {"store_id": store, "product_id": product, "review_period_days": 2}
    db.execute(insert(StoreProduct).values(row))
    assert _rejected(db, insert(StoreProduct).values(row))


def test_supervisor_must_belong_to_a_store(db: Connection) -> None:
    user = {"username": "nostore", "password_hash": "x", "name": "x", "role": "STORE_SUPERVISOR"}
    assert _rejected(db, insert(AppUser).values(user))
    assert not _rejected(db, insert(AppUser).values(user | {"role": "SUPER_ADMIN"}))


def test_business_rule_one_global_row_and_one_override_per_store(db: Connection) -> None:
    store = f.store(db)
    assert _rejected(db, insert(BusinessRule).values(rule_key="po_l2_threshold", value="1"))  # seeded by 0002
    assert not _rejected(
        db, insert(BusinessRule).values(rule_key="po_l2_threshold", value="1", scope_store_id=store)
    )
    assert _rejected(
        db, insert(BusinessRule).values(rule_key="po_l2_threshold", value="2", scope_store_id=store)
    )


def test_nightly_run_can_be_rerun_after_a_failure_but_never_twice_live(db: Connection) -> None:
    """D-35: unique (run_date) WHERE agent_name = 'nightly' AND status IN ('RUNNING','SUCCESS','PARTIAL')."""

    def start(status: str = "RUNNING", agent: str = "nightly", day: date = D) -> object:
        return insert(AgentRun).values(agent_name=agent, run_date=day, status=status)

    assert not _rejected(db, start("FAILED"))
    assert not _rejected(db, start("FAILED"))  # failures do not block anything
    assert not _rejected(db, start())  # re-run after the failure
    assert _rejected(db, start())  # a second live run for the same date
    assert _rejected(db, start("PARTIAL"))
    db.execute(
        update(AgentRun)
        .where(AgentRun.run_date == D, AgentRun.agent_name == "nightly", AgentRun.status == "RUNNING")
        .values(status="SUCCESS")
    )
    assert _rejected(db, start())  # a completed run blocks another
    assert not _rejected(db, start(agent="DemandForecasting"))  # child agents are not guarded
    assert not _rejected(db, start(day=date(2026, 11, 4)))  # the next date is free


# --- partitions, generated column ---------------------------------------------------------------------------------


def test_rows_are_routed_to_their_monthly_partition(db: Connection) -> None:
    store, product = f.store(db), f.product(db)
    for day in (date(2026, 11, 2), date(2030, 1, 1)):
        bill = uuid.uuid4()
        db.execute(
            insert(SalesTransaction).values(
                bill_id=bill,
                store_id=store,
                txn_datetime=datetime(day.year, day.month, day.day, tzinfo=UTC),
                txn_date=day,
                total_amount=Decimal("100"),
            )
        )
        db.execute(
            insert(SalesLine).values(
                bill_id=bill,
                line_no=1,
                txn_date=day,
                store_id=store,
                product_id=product,
                qty=1,
                unit_price=Decimal("100"),
            )
        )
    lines = db.execute(text("SELECT txn_date, tableoid::regclass::text FROM sales_line ORDER BY txn_date"))
    assert [tuple(r) for r in lines] == [
        (date(2026, 11, 2), "sales_line_2026_11"),
        (date(2030, 1, 1), "sales_line_default"),
    ]

    # month bounds are UTC: 2026-11-30 23:00 IST is still November in UTC terms
    late = datetime(2026, 11, 30, 17, 30, tzinfo=UTC)
    db.execute(
        insert(InventoryMovement).values(
            occurred_at=late,
            business_date=date(2026, 11, 30),
            store_id=store,
            product_id=product,
            movement_type="SALE",
            qty=-1,
            location="SHELF",
        )
    )
    where = db.execute(text("SELECT tableoid::regclass::text FROM inventory_movement")).scalar()
    assert where == "inventory_movement_2026_11"


def test_priority_rank_is_generated_for_the_indexed_rank_sort(db: Connection) -> None:
    store, product = f.store(db), f.product(db)
    high = f.recommendation(db, store, product, priority="HIGH")
    normal = f.recommendation(db, store, product)
    rows = db.execute(
        select(Recommendation.rec_id, Recommendation.priority_rank).where(
            Recommendation.rec_id.in_([high, normal])
        )
    )
    ranks = {rec_id: rank for rec_id, rank in rows}
    assert ranks == {high: 0, normal: 1}


# --- materialized views ---------------------------------------------------------------------------------------------


def test_materialized_views_refresh_concurrently_with_the_expected_figures(db: Connection) -> None:
    store, product, other = f.store(db), f.product(db), f.product(db)  # cost 60, price 100
    bill = uuid.uuid4()
    db.execute(
        insert(SalesTransaction).values(
            bill_id=bill,
            store_id=store,
            txn_datetime=datetime(2026, 11, 2, 10, tzinfo=UTC),
            txn_date=date(2026, 11, 2),
            total_amount=Decimal("190"),
        )
    )
    # executemany takes its column list from the first row, so every row names every column
    line = {"bill_id": bill, "txn_date": date(2026, 11, 2), "store_id": store, "product_id": product,
            "unit_price": Decimal("100"), "discount": Decimal("0"), "is_return": False, "is_voided": False}  # fmt: skip
    db.execute(
        insert(SalesLine),
        [
            line | {"line_no": 1, "qty": 2},  # 200
            line | {"line_no": 2, "qty": 1, "discount": Decimal("10")},  # 90
            line | {"line_no": 3, "qty": 1, "is_return": True},  # −100
            line | {"line_no": 4, "qty": 5, "is_voided": True},  # 0
        ],
    )
    snap = {"store_id": store, "snapshot_date": date(2026, 11, 2), "shelf_qty": 0, "backroom_qty": 0}
    db.execute(
        insert(InventoryDailySnapshot),
        [
            snap | {"product_id": product, "closing_on_hand": 4},
            snap | {"product_id": other, "closing_on_hand": 0},
        ],
    )
    supplier = f.supplier(db)
    run = f.agent_run(db, run_date=None, agent_name="test")
    rec = f.recommendation(db, store, product, run_id=run)
    po = f.purchase_order(db, supplier, run)
    db.execute(
        insert(POLine).values(
            po_id=po, store_id=store, product_id=product, qty=5, unit_price=Decimal("50"), source_rec_id=rec
        )
    )
    db.execute(
        insert(TransferOrder).values(
            from_store_id=f.store(db),
            to_store_id=store,
            product_id=product,
            qty=3,
            transfer_cost=Decimal("150"),
            transit_days=1,
            source_rec_id=rec,
        )
    )

    db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_dashboard_store_day"))
    db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_inbox_counts"))

    day = db.execute(
        text(
            "SELECT revenue, gross_profit, units, stockout_share FROM mv_dashboard_store_day WHERE store_id = :s"
        ),
        {"s": store},
    ).one()
    # revenue 200 + 90 − 100 = 190; cost of sold units 3 × 60 = 180 (returns are not restocked, voids never happened)
    assert tuple(day) == (Decimal("190.00"), Decimal("10.00"), 3, Decimal("0.5000"))
    inbox = db.execute(
        text(
            "SELECT pending_recommendations, pending_po_lines, transfers_to_accept FROM mv_inbox_counts "
            "WHERE store_id = :s"
        ),
        {"s": store},
    ).one()
    assert tuple(inbox) == (1, 1, 1)


# --- seed -----------------------------------------------------------------------------------------------------------


def test_seed_is_idempotent_and_creates_working_logins(engine: Engine) -> None:
    usernames = ["admin", "sup.a", "sup.b", "sup.c"]
    try:
        first = seed(engine, "s3cret-test")
        assert (first.stores_created, first.users_created) == (3, 4)
        second = seed(engine, "other-password")
        assert (second.stores_created, second.users_created) == (0, 0)
        with Session(engine) as session:
            users = {
                u.username: u for u in session.scalars(select(AppUser).where(AppUser.username.in_(usernames)))
            }
            assert set(users) == set(usernames)
            assert all(
                verify_password("s3cret-test", u.password_hash) for u in users.values()
            )  # not overwritten
            assert users["admin"].role == "SUPER_ADMIN" and users["admin"].store_id is None
            codes = {s.store_id: s.code for s in session.scalars(select(Store))}
            assert {codes[users[f"sup.{c}"].store_id] for c in "abc"} == {"A", "B", "C"}
            assert {s.store_id for s in STORES} <= set(codes)  # the generator's fixed ids (Phase 4b)
            assert (
                session.scalar(select(func.count()).select_from(Store).where(Store.code.in_(["A", "B", "C"])))
                == 3
            )
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM app_user WHERE username = ANY(:u)"), {"u": usernames})
            conn.execute(text("DELETE FROM store WHERE code IN ('A', 'B', 'C')"))


@pytest.mark.parametrize("table", ["recommendation", "po_line", "transfer_order"])
def test_status_defaults_start_workflows_at_their_first_state(db: Connection, table: str) -> None:
    default = db.execute(
        text(
            "SELECT column_default FROM information_schema.columns WHERE table_name = :t "
            "AND column_name IN ('status', 'line_status')"
        ),
        {"t": table},
    ).scalar()
    assert default is not None and default.split("'")[1] in {"PENDING", "PROPOSED"}
