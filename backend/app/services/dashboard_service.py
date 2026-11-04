"""Dashboard service: KPIs (SD-11 v3.1, D-35) and widget data (D-46), with Redis cache-aside.

- Calendar-day figures come from `mv_dashboard_store_day`; per-run figures from the latest successful nightly run
  (lost sales, forecasts) and `mv_inbox_counts`; stock from `inventory_position`, `batch`, `store_product`.
- The data day is the last day of history = the latest run's `run_date − 1` (a run plans the next day). Periods
  end on that day.
- Query errors propagate (500 with the standard body). Only the cache is fail-open (SD-11). Earlier versions
  swallowed every error and returned zeros; two queries referenced columns that do not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.schemas.common import ProductRef, StoreRef
from app.domain.schemas.dtos import (
    CategoryValueDTO,
    DashboardInsights,
    DashboardSummary,
    ExpiryDayDTO,
    MoverDTO,
    Period,
    POStatusCountDTO,
    SalesDayDTO,
    StockHealthDTO,
    StorePerformanceDTO,
)
from app.services.cache_service import CacheService
from app.tools.requirement import RequirementCalculator

EXPIRY_WINDOW_DAYS = 14
CACHE_TTL_S = 3600


@dataclass(frozen=True)
class RunInfo:
    run_id: UUID | None
    data_day: date


def period_bounds(period: Period, data_day: date) -> tuple[date, date]:
    """Inclusive [start, end] ending on the last day with data."""
    if period == "TODAY":
        return data_day, data_day
    if period == "LAST_7_DAYS":
        return data_day - timedelta(days=6), data_day
    if period == "LAST_28_DAYS":
        return data_day - timedelta(days=27), data_day
    return data_day.replace(day=1), data_day  # MONTH_TO_DATE


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class DashboardService:
    def __init__(self, cache: CacheService | None = None) -> None:
        self.cache = cache or CacheService()

    # --- shared ------------------------------------------------------------------------------------------------

    async def latest_run(self, session: AsyncSession) -> RunInfo:
        row = (
            await session.execute(
                text(
                    "SELECT run_id, run_date FROM agent_run WHERE agent_name = 'nightly' "
                    "AND status IN ('SUCCESS', 'PARTIAL') AND run_date IS NOT NULL "
                    "ORDER BY run_date DESC, started_at DESC LIMIT 1"
                )
            )
        ).one_or_none()
        if row is not None:
            self.cache.set_latest_run_id(row.run_id)
            return RunInfo(row.run_id, row.run_date - timedelta(days=1))
        last = (await session.execute(text("SELECT max(day) FROM mv_dashboard_store_day"))).scalar()
        return RunInfo(None, last or date.today() - timedelta(days=1))

    async def _store_ref(self, session: AsyncSession, store_id: UUID | None) -> StoreRef | None:
        if store_id is None:
            return None
        row = (
            await session.execute(
                text("SELECT store_id, name FROM store WHERE store_id = :s"), {"s": store_id}
            )
        ).one_or_none()
        return StoreRef(store_id=row.store_id, name=row.name) if row else None

    async def _stock_rows(
        self, session: AsyncSession, run_id: UUID | None, store_id: UUID | None
    ) -> list[Any]:
        """Listed store-SKUs with on hand, available, latest daily demand, lead time and review period."""
        return list(
            (
                await session.execute(
                    text(
                        """
                        SELECT sp.store_id,
                               COALESCE(ip.shelf_qty, 0) + COALESCE(ip.backroom_qty, 0) AS on_hand,
                               COALESCE(ip.shelf_qty, 0) + COALESCE(ip.backroom_qty, 0)
                                 + COALESCE(ip.incoming, 0) - COALESCE(ip.reserved, 0) AS available,
                               COALESCE(f.daily_demand, 0) AS daily_demand,
                               sst.lead_time_days AS terms_lead, spp.lead_time_days AS product_lead,
                               COALESCE(sup.default_lead_time_days, 0) AS default_lead,
                               sp.review_period_days
                        FROM store_product sp
                        LEFT JOIN inventory_position ip
                               ON ip.store_id = sp.store_id AND ip.product_id = sp.product_id
                        LEFT JOIN forecast f
                               ON f.run_id = :run_id AND f.store_id = sp.store_id AND f.product_id = sp.product_id
                        LEFT JOIN supplier_store_terms sst
                               ON sst.supplier_id = sp.preferred_supplier_id AND sst.store_id = sp.store_id
                        LEFT JOIN supplier_product spp
                               ON spp.supplier_id = sp.preferred_supplier_id AND spp.product_id = sp.product_id
                        LEFT JOIN supplier sup ON sup.supplier_id = sp.preferred_supplier_id
                        WHERE sp.is_listed AND (CAST(:store_id AS uuid) IS NULL OR sp.store_id = :store_id)
                        """
                    ),
                    {"run_id": run_id, "store_id": store_id},
                )
            ).all()
        )

    @staticmethod
    def _risk(row: Any) -> str:
        lead = RequirementCalculator.lead_time(row.terms_lead, row.product_lead, int(row.default_lead))
        return RequirementCalculator.stockout_risk(
            int(row.available), float(row.daily_demand), lead, int(row.review_period_days)
        )

    # --- KPIs (SD-11) ------------------------------------------------------------------------------------------

    async def get_summary(
        self, session: AsyncSession, store_id: UUID | None, period: Period = "LAST_28_DAYS"
    ) -> DashboardSummary:
        run = await self.latest_run(session)
        key = f"dash:{run.run_id}:{store_id or 'all'}:{period}"
        cached = self.cache.get(key)
        if cached:
            return DashboardSummary.model_validate_json(cached)

        start, end = period_bounds(period, run.data_day)
        scope = {"store_id": store_id, "start": start, "end": end}
        day = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(revenue), 0) AS revenue, COALESCE(SUM(gross_profit), 0) AS gp, "
                    "COALESCE(SUM(stockout_products)::float / NULLIF(SUM(products_tracked), 0), 0) AS stockout "
                    "FROM mv_dashboard_store_day WHERE (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id) "
                    "AND day BETWEEN :start AND :end"
                ),
                scope,
            )
        ).one()
        revenue, gross_profit = _money(day.revenue), _money(day.gp)
        lost = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(lost_revenue), 0) AS rev, COALESCE(SUM(lost_profit), 0) AS profit "
                    "FROM lost_sales_estimate WHERE run_id = :run_id "
                    "AND (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id)"
                ),
                {"run_id": run.run_id, "store_id": store_id},
            )
        ).one()
        stock = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM((ip.shelf_qty + ip.backroom_qty) * p.cost_price), 0) "
                    "FROM inventory_position ip JOIN product p ON p.product_id = ip.product_id "
                    "WHERE (CAST(:store_id AS uuid) IS NULL OR ip.store_id = :store_id)"
                ),
                {"store_id": store_id},
            )
        ).scalar()
        near_expiry = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(b.qty * p.cost_price), 0) FROM batch b "
                    "JOIN product p ON p.product_id = b.product_id WHERE b.qty > 0 AND b.expiry_date <= :cutoff "
                    "AND (CAST(:store_id AS uuid) IS NULL OR b.store_id = :store_id)"
                ),
                {"store_id": store_id, "cutoff": run.data_day + timedelta(days=EXPIRY_WINDOW_DAYS)},
            )
        ).scalar()
        inbox = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(pending_recommendations), 0) AS recs, "
                    "COALESCE(SUM(pending_po_lines), 0) AS po_lines, "
                    "COALESCE(SUM(transfers_to_accept + transfers_to_release + transfers_to_dispatch "
                    "+ transfers_to_receive), 0) AS transfers "
                    "FROM mv_inbox_counts WHERE (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id)"
                ),
                {"store_id": store_id},
            )
        ).one()
        movers_sql = (
            "SELECT p.product_id, p.sku, p.name, p.category, SUM(sl.qty) AS units, "
            "SUM(sl.qty * sl.unit_price - sl.discount) AS revenue FROM sales_line sl "
            "JOIN product p ON p.product_id = sl.product_id "
            "WHERE (CAST(:store_id AS uuid) IS NULL OR sl.store_id = :store_id) AND sl.txn_date BETWEEN :start AND :end "
            "AND NOT sl.is_voided AND NOT sl.is_return "
            "GROUP BY p.product_id, p.sku, p.name, p.category ORDER BY units {order}, p.sku LIMIT 5"
        )
        movers = {}
        for order in ("DESC", "ASC"):
            rows = (await session.execute(text(movers_sql.format(order=order)), scope)).all()
            movers[order] = [
                MoverDTO(
                    product=ProductRef(product_id=r.product_id, sku=r.sku, name=r.name, category=r.category),
                    units=int(r.units),
                    revenue=_money(r.revenue),
                )
                for r in rows
            ]

        summary = DashboardSummary(
            store=await self._store_ref(session, store_id),
            period=period,
            revenue=revenue,
            gross_profit=gross_profit,
            margin_pct=float(round(gross_profit / revenue * 100, 2)) if revenue > 0 else 0.0,
            stockout_rate=float(day.stockout),
            lost_revenue=_money(lost.rev),
            lost_profit=_money(lost.profit),
            inventory_value=_money(stock),
            near_expiry_value=_money(near_expiry),
            pending_recommendations=int(inbox.recs),
            pending_purchase_orders=int(inbox.po_lines),
            active_transfers=int(inbox.transfers),
            fast_movers=movers["DESC"],
            slow_movers=movers["ASC"],
        )
        self.cache.set(key, summary.model_dump_json(), ttl=CACHE_TTL_S)
        return summary

    # --- widget data (D-46) ----------------------------------------------------------------------------------------

    async def get_insights(
        self, session: AsyncSession, store_id: UUID | None, period: Period = "LAST_28_DAYS"
    ) -> DashboardInsights:
        run = await self.latest_run(session)
        key = f"dashi:{run.run_id}:{store_id or 'all'}:{period}"
        cached = self.cache.get(key)
        if cached:
            return DashboardInsights.model_validate_json(cached)

        start, end = period_bounds(period, run.data_day)
        scope = {"store_id": store_id, "start": start, "end": end}
        trend = (
            await session.execute(
                text(
                    "SELECT day, SUM(revenue) AS revenue, SUM(units) AS units FROM mv_dashboard_store_day "
                    "WHERE (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id) AND day BETWEEN :start AND :end "
                    "GROUP BY day ORDER BY day"
                ),
                scope,
            )
        ).all()
        forecast_total = None
        if run.run_id is not None:
            forecast_total = (
                await session.execute(
                    text(
                        "SELECT SUM(daily_demand) FROM forecast WHERE run_id = :run_id "
                        "AND (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id)"
                    ),
                    {"run_id": run.run_id, "store_id": store_id},
                )
            ).scalar()
        categories = (
            await session.execute(
                text(
                    "SELECT p.category, SUM((ip.shelf_qty + ip.backroom_qty) * p.cost_price) AS value, "
                    "SUM(ip.shelf_qty * p.cost_price) AS shelf, SUM(ip.backroom_qty * p.cost_price) AS backroom "
                    "FROM inventory_position ip JOIN product p ON p.product_id = ip.product_id "
                    "WHERE (CAST(:store_id AS uuid) IS NULL OR ip.store_id = :store_id) "
                    "GROUP BY p.category ORDER BY value DESC, p.category"
                ),
                {"store_id": store_id},
            )
        ).all()
        expiry = (
            await session.execute(
                text(
                    "SELECT b.expiry_date AS day, SUM(b.qty) AS qty, SUM(b.qty * p.cost_price) AS value FROM batch b "
                    "JOIN product p ON p.product_id = b.product_id WHERE b.qty > 0 "
                    "AND b.expiry_date BETWEEN :first AND :last "
                    "AND (CAST(:store_id AS uuid) IS NULL OR b.store_id = :store_id) "
                    "GROUP BY b.expiry_date ORDER BY b.expiry_date"
                ),
                {
                    "store_id": store_id,
                    "first": run.data_day + timedelta(days=1),
                    "last": run.data_day + timedelta(days=EXPIRY_WINDOW_DAYS),
                },
            )
        ).all()
        po_status = (
            await session.execute(
                text(
                    "SELECT po.status, COUNT(DISTINCT po.po_id) AS n, COALESCE(SUM(l.qty * l.unit_price), 0) AS value "
                    "FROM purchase_order po JOIN po_line l ON l.po_id = po.po_id "
                    "WHERE po.status <> 'SUPERSEDED' AND (CAST(:store_id AS uuid) IS NULL OR l.store_id = :store_id) "
                    "GROUP BY po.status ORDER BY po.status"
                ),
                {"store_id": store_id},
            )
        ).all()

        stock_rows = await self._stock_rows(session, run.run_id, store_id)
        health = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        high_by_store: dict[UUID, int] = {}
        out_of_stock = 0
        for row in stock_rows:
            risk = self._risk(row)
            health[risk] += 1
            if risk == "HIGH":
                high_by_store[row.store_id] = high_by_store.get(row.store_id, 0) + 1
            if int(row.on_hand) <= 0:
                out_of_stock += 1

        performance: list[StorePerformanceDTO] = []
        if store_id is None:
            per_store = (
                await session.execute(
                    text(
                        "SELECT s.store_id, s.name, COALESCE(SUM(m.revenue), 0) AS revenue, "
                        "COALESCE(SUM(m.stockout_products)::float / NULLIF(SUM(m.products_tracked), 0), 0) AS stockout "
                        "FROM store s LEFT JOIN mv_dashboard_store_day m "
                        "ON m.store_id = s.store_id AND m.day BETWEEN :start AND :end "
                        "GROUP BY s.store_id, s.name ORDER BY s.name"
                    ),
                    scope,
                )
            ).all()
            performance = [
                StorePerformanceDTO(
                    store=StoreRef(store_id=r.store_id, name=r.name),
                    revenue=_money(r.revenue),
                    stockout_rate=float(r.stockout),
                    high_risk_skus=high_by_store.get(r.store_id, 0),
                )
                for r in per_store
            ]

        insights = DashboardInsights(
            store=await self._store_ref(session, store_id),
            period=period,
            data_as_of=run.data_day if run.run_id is not None else None,
            forecast_units_per_day=float(forecast_total) if forecast_total is not None else None,
            sales_trend=[
                SalesDayDTO(day=r.day, revenue=_money(r.revenue), units=int(r.units)) for r in trend
            ],
            inventory_by_category=[
                CategoryValueDTO(category=r.category, value=_money(r.value)) for r in categories if r.value
            ],
            shelf_value=_money(sum((r.shelf or 0) for r in categories)),
            backroom_value=_money(sum((r.backroom or 0) for r in categories)),
            stock_health=StockHealthDTO(
                high_risk=health["HIGH"],
                medium_risk=health["MEDIUM"],
                low_risk=health["LOW"],
                out_of_stock=out_of_stock,
            ),
            expiry_next_14_days=[
                ExpiryDayDTO(day=r.day, qty=int(r.qty), value=_money(r.value)) for r in expiry
            ],
            po_status=[
                POStatusCountDTO(status=r.status, count=int(r.n), value=_money(r.value)) for r in po_status
            ],
            store_performance=performance,
        )
        self.cache.set(key, insights.model_dump_json(), ttl=CACHE_TTL_S)
        return insights
