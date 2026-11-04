"""Analytics (D-48): ABC-XYZ classification, category performance, forecast mix and top lost sales — computed."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.schemas.common import ProductRef, StoreRef
from app.domain.schemas.dtos import (
    AbcXyzCellDTO,
    AnalyticsDTO,
    CategoryPerformanceDTO,
    ForecastMixDTO,
    LostSalesItemDTO,
    Period,
)
from app.services.dashboard_service import DashboardService, _money, period_bounds

TOP_LOST = 10


class AnalyticsService:
    async def get(self, session: AsyncSession, store_id: UUID | None, period: Period) -> AnalyticsDTO:
        dash = DashboardService()
        run = await dash.latest_run(session)
        start, end = period_bounds(period, run.data_day)
        scope = {"store_id": store_id}
        abc = await session.execute(
            text(
                "SELECT abc_class, xyz_class, count(*) AS n FROM store_product WHERE is_listed "
                "AND abc_class IS NOT NULL AND xyz_class IS NOT NULL "
                "AND (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id) GROUP BY 1, 2 ORDER BY 1, 2"
            ),
            scope,
        )
        cats = await session.execute(
            text(
                "SELECT p.category, SUM(sl.qty * sl.unit_price - sl.discount) AS revenue, "
                "SUM(sl.qty * sl.unit_price - sl.discount - sl.qty * p.cost_price) AS gp, SUM(sl.qty) AS units "
                "FROM sales_line sl JOIN product p ON p.product_id = sl.product_id "
                "WHERE NOT sl.is_return AND NOT sl.is_voided AND sl.txn_date BETWEEN :start AND :end "
                "AND (CAST(:store_id AS uuid) IS NULL OR sl.store_id = :store_id) "
                "GROUP BY p.category ORDER BY revenue DESC, p.category"
            ),
            scope | {"start": start, "end": end},
        )
        mix = await session.execute(
            text(
                "SELECT method, confidence, count(*) AS n FROM forecast WHERE run_id = :run_id "
                "AND (CAST(:store_id AS uuid) IS NULL OR store_id = :store_id) GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2"
            ),
            scope | {"run_id": run.run_id},
        )
        lost = await session.execute(
            text(
                "SELECT s.store_id, s.name AS store_name, p.product_id, p.sku, p.name, p.category, l.lost_units, "
                "l.lost_revenue, l.lost_profit FROM lost_sales_estimate l "
                "JOIN store s ON s.store_id = l.store_id JOIN product p ON p.product_id = l.product_id "
                "WHERE l.run_id = :run_id AND l.lost_revenue > 0 "
                "AND (CAST(:store_id AS uuid) IS NULL OR l.store_id = :store_id) "
                "ORDER BY l.lost_revenue DESC, p.sku LIMIT :n"
            ),
            scope | {"run_id": run.run_id, "n": TOP_LOST},
        )
        categories = []
        for r in cats:
            revenue, gp = _money(r.revenue), _money(r.gp)
            categories.append(
                CategoryPerformanceDTO(
                    category=r.category,
                    revenue=revenue,
                    gross_profit=gp,
                    margin_pct=float(round(gp / revenue * 100, 2)) if revenue > 0 else 0.0,
                    units=int(r.units),
                )
            )
        return AnalyticsDTO(
            store=await dash._store_ref(session, store_id),
            period=period,
            data_as_of=run.data_day if run.run_id is not None else None,
            abc_xyz=[AbcXyzCellDTO(abc=r.abc_class, xyz=r.xyz_class, skus=int(r.n)) for r in abc],
            categories=categories,
            forecast_mix=[
                ForecastMixDTO(method=r.method, confidence=r.confidence, skus=int(r.n)) for r in mix
            ],
            top_lost_sales=[
                LostSalesItemDTO(
                    store=StoreRef(store_id=r.store_id, name=r.store_name),
                    product=ProductRef(product_id=r.product_id, sku=r.sku, name=r.name, category=r.category),
                    lost_units=round(float(r.lost_units), 1),
                    lost_revenue=_money(r.lost_revenue),
                    lost_profit=_money(r.lost_profit),
                )
                for r in lost
            ],
        )
