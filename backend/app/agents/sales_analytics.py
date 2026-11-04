"""Sales Analytics Agent (SD-03, spec §8).

Computes revenue, margin, and stockout KPIs over the lookback window, and estimates lost sales
for days when stock was depleted.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pandas as pd
from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.inventory import InventoryDailySnapshot
from app.domain.models.master import Product
from app.domain.models.planning import KpiSnapshot, LostSalesEstimate
from app.domain.models.sales import SalesLine
from app.domain.repositories.planning_repo import PlanningRepo
from app.tools.lost_sales import LostSalesCalculator


class SalesAnalyticsAgent(BaseAgent):
    name = "SalesAnalyticsAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        start_date = ctx.run_date - timedelta(days=ctx.params.kpi_lookback_days)

        # 1. Fetch sales lines
        stmt_sales = select(
            SalesLine.store_id,
            SalesLine.product_id,
            SalesLine.txn_date,
            SalesLine.qty,
            (SalesLine.unit_price * SalesLine.qty - SalesLine.discount).label("revenue"),
        ).where(
            SalesLine.store_id.in_(ctx.store_ids),
            SalesLine.txn_date >= start_date,
            SalesLine.txn_date < ctx.run_date,
            SalesLine.is_voided.is_(False),
            SalesLine.is_return.is_(False),
            SalesLine.qty > 0,
        )
        sales_rows = ctx.session.execute(stmt_sales).all()
        if sales_rows:
            sales_df = pd.DataFrame(
                [
                    {
                        "store_id": r.store_id,
                        "product_id": r.product_id,
                        "day": r.txn_date,
                        "units": r.qty,
                        "revenue": float(r.revenue),
                    }
                    for r in sales_rows
                ]
            )
        else:
            sales_df = pd.DataFrame(columns=["store_id", "product_id", "day", "units", "revenue"])

        # 2. Fetch stockout days (closing_on_hand == 0)
        stmt_stockout = select(
            InventoryDailySnapshot.store_id,
            InventoryDailySnapshot.product_id,
            InventoryDailySnapshot.snapshot_date.label("day"),
        ).where(
            InventoryDailySnapshot.store_id.in_(ctx.store_ids),
            InventoryDailySnapshot.snapshot_date >= start_date,
            InventoryDailySnapshot.snapshot_date < ctx.run_date,
            InventoryDailySnapshot.closing_on_hand == 0,
        )
        stockout_rows = ctx.session.execute(stmt_stockout).all()
        if stockout_rows:
            stockout_df = pd.DataFrame(
                [{"store_id": r.store_id, "product_id": r.product_id, "day": r.day} for r in stockout_rows]
            )
        else:
            stockout_df = pd.DataFrame(columns=["store_id", "product_id", "day"])

        # 3. Product margins
        products = ctx.session.scalars(select(Product)).all()
        margins_df = pd.DataFrame(
            [
                {
                    "product_id": p.product_id,
                    "unit_margin": float(p.selling_price - p.cost_price),
                    "selling_price": float(p.selling_price),
                }
                for p in products
            ]
        )

        # 4. Lost sales estimation via LostSalesCalculator
        lost_sales_records: list[LostSalesEstimate] = []
        if not sales_df.empty and not stockout_df.empty:
            calc_df = LostSalesCalculator.estimate(sales_df, stockout_df, margins_df)
            for row in calc_df.itertuples():
                store_id = row.store_id
                product_id = row.product_id
                lost_u = float(cast(Any, row.lost_units))
                lost_r = round(float(cast(Any, row.lost_revenue)), 2)
                lost_p = round(float(cast(Any, row.lost_profit)), 2)
                conf = str(row.confidence)
                lost_sales_records.append(
                    LostSalesEstimate(
                        run_id=ctx.run_id,
                        store_id=store_id,
                        product_id=product_id,
                        lost_units=lost_u,
                        lost_revenue=Decimal(str(lost_r)),
                        lost_profit=Decimal(str(lost_p)),
                        confidence=conf,
                    )
                )
            planning_repo.save_lost_sales(ctx.run_id, lost_sales_records)

        # 5. Store KPIs
        kpi_records: list[KpiSnapshot] = []
        total_rev = sales_df["revenue"].sum() if not sales_df.empty else 0.0
        nil_uuid = uuid.UUID(int=0)
        for s_id in ctx.store_ids:
            store_sales = sales_df.loc[sales_df["store_id"] == s_id] if not sales_df.empty else sales_df
            store_rev = (
                Decimal(str(round(store_sales["revenue"].sum(), 2)))
                if not store_sales.empty
                else Decimal("0")
            )
            kpi_records.append(
                KpiSnapshot(
                    run_id=ctx.run_id,
                    store_id=s_id,
                    metric="revenue_28d",
                    product_key=nil_uuid,
                    value=store_rev,
                )
            )
        planning_repo.save_kpis(ctx.run_id, kpi_records)

        return AgentResult(
            status="SUCCESS",
            outputs={
                "kpis": len(kpi_records),
                "lost_sales_rows": len(lost_sales_records),
                "total_revenue": total_rev,
            },
            step_count=5,
        )
