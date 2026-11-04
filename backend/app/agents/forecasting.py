"""Demand Forecasting Agent (SD-04, spec §8).

Computes ABC/XYZ classifications and generates store-SKU baseline forecasts.
Stale SKUs and products with limited in-stock history are tagged with LOW confidence.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pandas as pd
from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.inventory import InventoryDailySnapshot
from app.domain.models.master import StoreProduct
from app.domain.models.planning import Forecast
from app.domain.models.sales import SalesLine
from app.domain.repositories.planning_repo import PlanningRepo
from app.tools.forecast import ForecastTools


class DemandForecastingAgent(BaseAgent):
    name = "DemandForecastingAgent"
    critical = True

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        lookback_start = ctx.run_date - timedelta(days=ctx.params.forecast_lookback_days)

        # 1. Fetch sales series
        stmt_sales = select(
            SalesLine.store_id,
            SalesLine.product_id,
            SalesLine.txn_date.label("ds"),
            SalesLine.qty.label("y"),
            (SalesLine.unit_price * SalesLine.qty - SalesLine.discount).label("revenue"),
        ).where(
            SalesLine.store_id.in_(ctx.store_ids),
            SalesLine.txn_date >= lookback_start,
            SalesLine.txn_date < ctx.run_date,
            SalesLine.is_voided.is_(False),
            SalesLine.is_return.is_(False),
            SalesLine.qty > 0,
        )
        sales_rows = ctx.session.execute(stmt_sales).all()
        if not sales_rows:
            return AgentResult(status="SUCCESS", outputs={"forecasts": 0, "low_confidence": 0}, step_count=1)

        raw_df = pd.DataFrame(
            [
                {
                    "store_id": r.store_id,
                    "product_id": r.product_id,
                    "unique_id": f"{r.store_id}:{r.product_id}",
                    "ds": r.ds,
                    "y": float(r.y),
                    "revenue": float(r.revenue),
                }
                for r in sales_rows
            ]
        )

        # 2. Fetch stockout days to exclude from baseline (D-30)
        stmt_stockout = select(
            InventoryDailySnapshot.store_id,
            InventoryDailySnapshot.product_id,
            InventoryDailySnapshot.snapshot_date.label("ds"),
        ).where(
            InventoryDailySnapshot.store_id.in_(ctx.store_ids),
            InventoryDailySnapshot.snapshot_date >= lookback_start,
            InventoryDailySnapshot.snapshot_date < ctx.run_date,
            InventoryDailySnapshot.closing_on_hand == 0,
        )
        stockout_rows = ctx.session.execute(stmt_stockout).all()
        stockout_set = {(r.store_id, r.product_id, r.ds) for r in stockout_rows}

        raw_df["is_stockout"] = [
            (s, p, d) in stockout_set
            for s, p, d in zip(raw_df["store_id"], raw_df["product_id"], raw_df["ds"], strict=True)
        ]

        # 3. ABC / XYZ classification
        classified = ForecastTools.classify_abc_xyz(raw_df[["unique_id", "ds", "y", "revenue"]])
        for row in classified.itertuples():
            uid_str = str(row.unique_id)
            sid_str, pid_str = uid_str.split(":")
            sid, pid = UUID(sid_str), UUID(pid_str)
            sp = ctx.session.scalars(
                select(StoreProduct).where(StoreProduct.store_id == sid, StoreProduct.product_id == pid)
            ).one_or_none()
            if sp:
                sp.abc_class = str(row.abc)
                sp.xyz_class = str(row.xyz)

        # 4. Baseline daily demand
        baseline = ForecastTools.baseline_avg_daily(
            raw_df[["unique_id", "ds", "y", "is_stockout"]],
            window_days=ctx.params.kpi_lookback_days,
        )

        stale_set = set(ctx.stale_skus)
        forecast_models: list[Forecast] = []
        low_confidence_count = 0

        for row in baseline.itertuples():
            uid_str = str(row.unique_id)
            sid_str, pid_str = uid_str.split(":")
            store_id, product_id = UUID(sid_str), UUID(pid_str)

            confidence = "HIGH"
            in_stock_days = int(cast(Any, row.in_stock_days))
            if (store_id, product_id) in stale_set or in_stock_days < 7:
                confidence = "LOW"
                low_confidence_count += 1

            forecast_models.append(
                Forecast(
                    run_id=ctx.run_id,
                    store_id=store_id,
                    product_id=product_id,
                    horizon_days=ctx.params.forecast_horizon_days,
                    daily_demand=float(cast(Any, row.daily_demand)),
                    method="BASELINE",
                    confidence=confidence,
                )
            )

        planning_repo.bulk_insert_forecasts(ctx.run_id, forecast_models)
        ctx.session.flush()

        return AgentResult(
            status="SUCCESS",
            outputs={"forecasts": len(forecast_models), "low_confidence": low_confidence_count},
            step_count=4,
        )
