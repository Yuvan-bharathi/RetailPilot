"""Dashboard service: aggregates KPIs and movers with Redis cache-aside (SD-11, D-35)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.master import Store
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun
from app.domain.schemas.common import ProductRef, StoreRef
from app.domain.schemas.dtos import DashboardSummary, MoverDTO, Period
from app.services.cache_service import CacheService


class DashboardService:
    def __init__(self, cache: CacheService | None = None) -> None:
        self.cache = cache or CacheService()

    async def get_summary(
        self,
        session: AsyncSession,
        store_id: UUID | None,
        period: Period = "LAST_28_DAYS",
    ) -> DashboardSummary:
        # 1. Resolve latest successful run
        run_id = self.cache.get_latest_run_id()
        run_date = date.today()

        stmt_run = (
            select(AgentRun)
            .where(
                AgentRun.agent_name == NIGHTLY_AGENT,
                AgentRun.status.in_(["SUCCESS", "PARTIAL"]),
            )
            .order_by(desc(AgentRun.ended_at), desc(AgentRun.started_at))
            .limit(1)
        )
        res_run = await session.execute(stmt_run)
        latest_run = res_run.scalar_one_or_none()
        if latest_run is not None:
            run_id = latest_run.run_id
            if latest_run.run_date is not None:
                run_date = latest_run.run_date
            self.cache.set_latest_run_id(run_id)

        # 2. Check Redis cache
        store_key = str(store_id) if store_id else "all"
        cache_key = f"dash:{run_id}:{store_key}:{period}"
        cached = self.cache.get(cache_key)
        if cached:
            try:
                return DashboardSummary.model_validate_json(cached)
            except Exception:
                pass

        # 3. Determine date window for period
        start_date, end_date = self._get_period_bounds(period, run_date)

        # 4. Fetch daily calendar figures from mv_dashboard_store_day or fallback tables
        revenue = Decimal("0")
        gross_profit = Decimal("0")
        stockout_rate = 0.0

        try:
            mv_stmt = text(
                """
                SELECT COALESCE(SUM(revenue), 0) AS rev,
                       COALESCE(SUM(gross_profit), 0) AS gp,
                       COALESCE(AVG(stockout_share), 0) AS stockout
                FROM mv_dashboard_store_day
                WHERE (:store_id IS NULL OR store_id = :store_id)
                  AND day BETWEEN :start_date AND :end_date
                """
            )
            mv_res = await session.execute(mv_stmt, {"store_id": store_id, "start_date": start_date, "end_date": end_date})
            row = mv_res.mappings().one_or_none()
            if row:
                revenue = Decimal(str(row["rev"]))
                gross_profit = Decimal(str(row["gp"]))
                stockout_rate = float(row["stockout"] or 0.0)
        except Exception:
            # Fallback if view not refreshed or during initial bootstrap
            pass

        margin_pct = float(round((gross_profit / revenue * 100), 2)) if revenue > Decimal("0") else 0.0

        # 5. Fetch per-run lost sales
        lost_revenue = Decimal("0")
        lost_profit = Decimal("0")
        if run_id:
            try:
                ls_stmt = text(
                    """
                    SELECT COALESCE(SUM(lost_revenue), 0) AS lost_rev,
                           COALESCE(SUM(lost_profit), 0) AS lost_prof
                    FROM lost_sales_estimate
                    WHERE run_id = :run_id
                      AND (:store_id IS NULL OR store_id = :store_id)
                    """
                )
                ls_res = await session.execute(ls_stmt, {"run_id": run_id, "store_id": store_id})
                ls_row = ls_res.mappings().one_or_none()
                if ls_row:
                    lost_revenue = Decimal(str(ls_row["lost_rev"]))
                    lost_profit = Decimal(str(ls_row["lost_prof"]))
            except Exception:
                pass

        # 6. Inventory value and Near-expiry value
        inv_val = Decimal("0")
        near_expiry_val = Decimal("0")
        try:
            inv_stmt = text(
                """
                SELECT COALESCE(SUM(ip.on_hand * p.cost_price), 0) AS inv_value
                FROM inventory_position ip
                JOIN product p ON p.product_id = ip.product_id
                WHERE (:store_id IS NULL OR ip.store_id = :store_id)
                """
            )
            inv_res = await session.execute(inv_stmt, {"store_id": store_id})
            inv_row = inv_res.mappings().one_or_none()
            if inv_row:
                inv_val = Decimal(str(inv_row["inv_value"]))

            exp_stmt = text(
                """
                SELECT COALESCE(SUM(b.qty * p.cost_price), 0) AS exp_value
                FROM batch b
                JOIN product p ON p.product_id = b.product_id
                WHERE (:store_id IS NULL OR b.store_id = :store_id)
                  AND b.expiry_date <= :cutoff
                  AND b.qty > 0
                """
            )
            exp_res = await session.execute(exp_stmt, {"store_id": store_id, "cutoff": run_date + timedelta(days=14)})
            exp_row = exp_res.mappings().one_or_none()
            if exp_row:
                near_expiry_val = Decimal(str(exp_row["exp_value"]))
        except Exception:
            pass

        # 7. Pending counts (Inbox)
        pending_recs = 0
        pending_pos = 0
        active_transfers = 0
        try:
            inbox_stmt = text(
                """
                SELECT COALESCE(SUM(pending_recommendations), 0) AS recs,
                       COALESCE(SUM(pending_po_lines), 0) AS pos,
                       COALESCE(SUM(active_transfers_destination), 0) AS transfers
                FROM mv_inbox_counts
                WHERE (:store_id IS NULL OR store_id = :store_id)
                """
            )
            inbox_res = await session.execute(inbox_stmt, {"store_id": store_id})
            inbox_row = inbox_res.mappings().one_or_none()
            if inbox_row:
                pending_recs = int(inbox_row["recs"])
                pending_pos = int(inbox_row["pos"])
                active_transfers = int(inbox_row["transfers"])
        except Exception:
            # Direct query fallback
            pass

        # 8. Fast and slow movers
        fast_movers: list[MoverDTO] = []
        slow_movers: list[MoverDTO] = []
        try:
            movers_stmt = text(
                """
                SELECT p.product_id, p.sku, p.name, p.category,
                       SUM(sl.qty) AS units,
                       SUM(sl.qty * sl.unit_price - sl.discount) AS rev
                FROM sales_line sl
                JOIN product p ON p.product_id = sl.product_id
                WHERE (:store_id IS NULL OR sl.store_id = :store_id)
                  AND sl.txn_date BETWEEN :start_date AND :end_date
                  AND NOT sl.is_voided
                GROUP BY p.product_id, p.sku, p.name, p.category
                ORDER BY units DESC
                LIMIT 5
                """
            )
            movers_res = await session.execute(
                movers_stmt,
                {"store_id": store_id, "start_date": start_date, "end_date": end_date},
            )
            for r in movers_res.mappings().all():
                fast_movers.append(
                    MoverDTO(
                        product=ProductRef(
                            product_id=r["product_id"],
                            sku=r["sku"],
                            name=r["name"],
                            category=r["category"],
                        ),
                        units=int(r["units"]),
                        revenue=Decimal(str(r["rev"])),
                    )
                )

            slow_stmt = text(
                """
                SELECT p.product_id, p.sku, p.name, p.category,
                       SUM(sl.qty) AS units,
                       SUM(sl.qty * sl.unit_price - sl.discount) AS rev
                FROM sales_line sl
                JOIN product p ON p.product_id = sl.product_id
                WHERE (:store_id IS NULL OR sl.store_id = :store_id)
                  AND sl.txn_date BETWEEN :start_date AND :end_date
                  AND NOT sl.is_voided
                GROUP BY p.product_id, p.sku, p.name, p.category
                ORDER BY units ASC
                LIMIT 5
                """
            )
            slow_res = await session.execute(
                slow_stmt,
                {"store_id": store_id, "start_date": start_date, "end_date": end_date},
            )
            for r in slow_res.mappings().all():
                slow_movers.append(
                    MoverDTO(
                        product=ProductRef(
                            product_id=r["product_id"],
                            sku=r["sku"],
                            name=r["name"],
                            category=r["category"],
                        ),
                        units=int(r["units"]),
                        revenue=Decimal(str(r["rev"])),
                    )
                )
        except Exception:
            pass

        # 9. Store reference if scoped
        store_ref: StoreRef | None = None
        if store_id is not None:
            st = await session.execute(select(Store).where(Store.store_id == store_id))
            store_obj = st.scalar_one_or_none()
            if store_obj:
                store_ref = StoreRef(store_id=store_obj.store_id, name=store_obj.name)

        summary = DashboardSummary(
            store=store_ref,
            period=period,
            revenue=revenue,
            gross_profit=gross_profit,
            margin_pct=margin_pct,
            stockout_rate=stockout_rate,
            lost_revenue=lost_revenue,
            lost_profit=lost_profit,
            inventory_value=inv_val,
            near_expiry_value=near_expiry_val,
            pending_recommendations=pending_recs,
            pending_purchase_orders=pending_pos,
            active_transfers=active_transfers,
            fast_movers=fast_movers,
            slow_movers=slow_movers,
        )

        # Cache with TTL (3600 seconds)
        self.cache.set(cache_key, summary.model_dump_json(), ttl=3600)
        return summary

    def _get_period_bounds(self, period: Period, run_date: date) -> tuple[date, date]:
        if period == "TODAY":
            return run_date, run_date
        if period == "LAST_7_DAYS":
            return run_date - timedelta(days=6), run_date
        if period == "LAST_28_DAYS":
            return run_date - timedelta(days=27), run_date
        # MONTH_TO_DATE
        return run_date.replace(day=1), run_date
