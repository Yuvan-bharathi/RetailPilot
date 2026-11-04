"""DashboardService on PostgreSQL (SD-11, D-46): every figure is computed from the rows, nothing is defaulted.

Regression: the previous service queried `inventory_position.on_hand` and `mv_inbox_counts.active_transfers_
destination` (neither exists) inside `except Exception: pass`, so the dashboard returned zeros and the UI showed
typed-in sample numbers instead.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import URL, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import build_async_engine
from app.domain.models import (
    AgentRun,
    Batch,
    Forecast,
    InventoryDailySnapshot,
    InventoryPosition,
    POLine,
    Product,
    PurchaseOrder,
    Recommendation,
    SalesLine,
    SalesTransaction,
    Store,
    StoreProduct,
    Supplier,
    SupplierStoreTerms,
)
from app.services.dashboard_service import DashboardService, period_bounds

RUN_DATE = date(2030, 1, 2)  # later than any other test's run, so it is "the latest"
DAY = RUN_DATE - timedelta(days=1)


class NoCache:
    def get(self, key: str) -> None:
        return None

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        return True

    def set_latest_run_id(self, run_id: Any) -> None:
        return None


@pytest.fixture
async def session(migrated_url: URL) -> AsyncIterator[AsyncSession]:
    engine = build_async_engine(Settings(database_url=migrated_url.render_as_string(hide_password=False)))
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        finally:
            await trans.rollback()
    await engine.dispose()


async def _seed(s: AsyncSession) -> dict[str, Any]:
    store, product, other, supplier = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run = uuid.uuid4()
    await s.execute(insert(Store).values(store_id=store, code=f"T{store.hex[:6]}", name="Dash store", region="T",
                                         store_type="t", display_capacity=10))  # fmt: skip
    for pid, sku, cat in (
        (product, f"D-{product.hex[:6]}", "dairy"),
        (other, f"S-{other.hex[:6]}", "staples"),
    ):
        await s.execute(insert(Product).values(product_id=pid, sku=sku, name=sku, category=cat, brand="b",
                                               cost_price=Decimal("60"), selling_price=Decimal("100")))  # fmt: skip
    await s.execute(insert(Supplier).values(supplier_id=supplier, name="sup", default_lead_time_days=7))
    await s.execute(insert(SupplierStoreTerms).values(supplier_id=supplier, store_id=store, lead_time_days=3,
                                                      delivery_charge=Decimal("0")))  # fmt: skip
    for pid in (product, other):
        await s.execute(insert(StoreProduct).values(store_id=store, product_id=pid, preferred_supplier_id=supplier,
                                                    review_period_days=2))  # fmt: skip
    # product: 4 shelf + 6 backroom = 10 available, demand 10/day → 1 day of cover < lead 3 → HIGH
    # other: nothing on hand → out of stock (and HIGH)
    await s.execute(
        insert(InventoryPosition).values(store_id=store, product_id=product, shelf_qty=4, backroom_qty=6)
    )
    await s.execute(
        insert(AgentRun).values(run_id=run, agent_name="nightly", status="SUCCESS", run_date=RUN_DATE)
    )
    await s.execute(insert(Forecast).values(run_id=run, store_id=store, product_id=product, horizon_days=14,
                                            daily_demand=10.0, method="BASELINE", confidence="HIGH"))  # fmt: skip
    bill = uuid.uuid4()
    await s.execute(insert(SalesTransaction).values(bill_id=bill, store_id=store, txn_date=DAY,
                    txn_datetime=datetime(2030, 1, 1, 10, tzinfo=UTC), total_amount=Decimal("300")))  # fmt: skip
    line = {"bill_id": bill, "txn_date": DAY, "store_id": store, "product_id": product, "unit_price": Decimal("100"),
            "discount": Decimal("0"), "is_return": False, "is_voided": False}  # fmt: skip
    await s.execute(insert(SalesLine), [line | {"line_no": 1, "qty": 2}, line | {"line_no": 2, "qty": 1}])
    snap = {"store_id": store, "snapshot_date": DAY, "shelf_qty": 0, "backroom_qty": 0}
    await s.execute(insert(InventoryDailySnapshot), [snap | {"product_id": product, "closing_on_hand": 10},
                                                     snap | {"product_id": other, "closing_on_hand": 0}])  # fmt: skip
    await s.execute(insert(Batch).values(store_id=store, product_id=product, batch_no="B1", qty=5,
                                         expiry_date=DAY + timedelta(days=2)))  # fmt: skip
    rec = uuid.uuid4()
    await s.execute(insert(Recommendation).values(rec_id=rec, run_id=run, store_id=store, product_id=product,
                                                  rec_type="REORDER", qty=20, evidence={}))  # fmt: skip
    po = uuid.uuid4()
    await s.execute(insert(PurchaseOrder).values(po_id=po, supplier_id=supplier, run_id=run,
                                                 total_value=Decimal("250"), status="PENDING_L1"))  # fmt: skip
    await s.execute(insert(POLine).values(po_id=po, store_id=store, product_id=product, qty=5,
                                          unit_price=Decimal("50"), source_rec_id=rec))  # fmt: skip
    await s.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_dashboard_store_day"))
    await s.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_inbox_counts"))
    return {"store": store, "run": run}


async def test_summary_kpis_come_from_the_rows(session: AsyncSession) -> None:
    ids = await _seed(session)
    summary = await DashboardService(cache=NoCache()).get_summary(session, ids["store"], "TODAY")  # type: ignore[arg-type]

    assert summary.store is not None and summary.store.name == "Dash store"
    assert (summary.revenue, summary.gross_profit) == (Decimal("300.00"), Decimal("120.00"))  # 3 × (100 − 60)
    assert summary.stockout_rate == 0.5  # 1 of 2 tracked products closed at 0
    assert summary.inventory_value == Decimal("600.00")  # 10 on hand × 60
    assert summary.near_expiry_value == Decimal("300.00")  # 5 × 60, expires within 14 days
    assert (summary.pending_recommendations, summary.pending_purchase_orders) == (1, 1)
    assert [m.units for m in summary.fast_movers] == [3]


async def test_insights_breakdowns(session: AsyncSession) -> None:
    ids = await _seed(session)
    insights = await DashboardService(cache=NoCache()).get_insights(session, ids["store"], "TODAY")  # type: ignore[arg-type]

    assert insights.data_as_of == DAY
    assert insights.forecast_units_per_day == 10.0
    assert [(d.day, d.units) for d in insights.sales_trend] == [(DAY, 3)]
    assert [(c.category, c.value) for c in insights.inventory_by_category] == [("dairy", Decimal("600.00"))]
    assert (insights.shelf_value, insights.backroom_value) == (Decimal("240.00"), Decimal("360.00"))
    health = insights.stock_health
    assert (health.high_risk, health.medium_risk, health.low_risk, health.out_of_stock) == (2, 0, 0, 1)
    assert [(e.day, e.qty) for e in insights.expiry_next_14_days] == [(DAY + timedelta(days=2), 5)]
    assert [(p.status, p.count, p.value) for p in insights.po_status] == [
        ("PENDING_L1", 1, Decimal("250.00"))
    ]
    assert insights.store_performance == []  # store-scoped view


async def test_all_stores_view_lists_store_performance(session: AsyncSession) -> None:
    ids = await _seed(session)
    insights = await DashboardService(cache=NoCache()).get_insights(session, None, "TODAY")  # type: ignore[arg-type]
    mine = next(p for p in insights.store_performance if p.store.store_id == ids["store"])
    assert (mine.revenue, mine.stockout_rate, mine.high_risk_skus) == (Decimal("300.00"), 0.5, 2)


def test_periods_end_on_the_last_day_with_data() -> None:
    day = date(2026, 11, 2)
    assert period_bounds("TODAY", day) == (day, day)
    assert period_bounds("LAST_7_DAYS", day) == (date(2026, 10, 27), day)
    assert period_bounds("LAST_28_DAYS", day) == (date(2026, 10, 6), day)
    assert period_bounds("MONTH_TO_DATE", day) == (date(2026, 11, 1), day)


async def test_inventory_rows_use_rule_1_requirement_and_the_same_risk(session: AsyncSession) -> None:
    """Regression: the inventory view used a hard-coded 2-day lead time, no min display and 5 units/day when no
    forecast existed. Rule 1: ceil(d × (lead of THIS store's supplier + review)) + ceil(d × safety) + min display."""
    from app.domain.models import AppUser
    from app.services.inventory_view_service import InventoryViewService

    ids = await _seed(session)
    admin = AppUser(username="x", password_hash="x", name="x", role="SUPER_ADMIN")
    view = await InventoryViewService().get_view(session, ids["store"], admin, page_size=10)
    rows = {r.product.category: r for r in view.items}
    dairy = rows["dairy"]  # demand 10/day, lead 3 (store terms, not the supplier default 7), review 2
    assert (dairy.available, dairy.own_requirement, dairy.surplus_or_shortage) == (10, 50, -40)
    assert (dairy.days_of_cover, dairy.stockout_risk) == (1.0, "HIGH")
    staples = rows["staples"]  # no forecast → demand 0, not a guessed 5/day
    assert (staples.own_requirement, staples.stockout_risk) == (0, "HIGH")  # nothing on hand: 0 days of cover
