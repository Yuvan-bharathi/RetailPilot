"""Demand Forecasting Agent (SD-04, spec §8, D-30, D-45).

1. Daily sales per store-SKU over the lookback (net sale units and revenue per day — not per bill line), zero-filled
   from the start of the lookback to the day before the run for every store-SKU sold in it.
2. Stockout days (closing on hand = 0) are flagged and excluded from the demand estimate (D-30).
3. ABC/XYZ per store (one bulk update).
4. Baseline = mean daily demand over the in-stock days of the last `kpi_lookback_days`.
5. Model selection (D-45, `use_model_selection`): ETS / Croston-SBA / TSB replace the baseline for a store-SKU only
   when a rolling-origin backtest shows a clear improvement.
Stale SKUs and products with fewer than 7 in-stock days are LOW confidence (D-04).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pandas as pd
from sqlalchemy import func, select, update

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.inventory import InventoryDailySnapshot
from app.domain.models.master import StoreProduct
from app.domain.models.planning import Forecast
from app.domain.models.sales import SalesLine
from app.domain.repositories.planning_repo import PlanningRepo
from app.tools.forecast import ForecastTools

MIN_IN_STOCK_DAYS = 7


def daily_series(
    rows: list[Any], start: Any, end_exclusive: Any, stockouts: set[tuple[Any, Any, Any]]
) -> pd.DataFrame:
    """Zero-filled daily frame [store_id, product_id, unique_id, ds, y, revenue, is_stockout] (oldest first)."""
    sales = pd.DataFrame(
        [(r.store_id, r.product_id, r.ds, float(r.y), float(r.revenue)) for r in rows],
        columns=["store_id", "product_id", "ds", "y", "revenue"],
    )
    days = pd.date_range(start, end_exclusive - timedelta(days=1), freq="D").date
    keys = sales[["store_id", "product_id"]].drop_duplicates()
    grid = keys.merge(pd.DataFrame({"ds": days}), how="cross")
    frame = grid.merge(sales, on=["store_id", "product_id", "ds"], how="left").fillna(
        {"y": 0.0, "revenue": 0.0}
    )
    frame["unique_id"] = frame["store_id"].astype(str) + ":" + frame["product_id"].astype(str)
    frame["is_stockout"] = [
        (s, p, d) in stockouts
        for s, p, d in zip(frame["store_id"], frame["product_id"], frame["ds"], strict=True)
    ]
    return frame.sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True)


class DemandForecastingAgent(BaseAgent):
    name = "DemandForecastingAgent"
    critical = True

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        params = ctx.params
        lookback_start = ctx.run_date - timedelta(days=params.forecast_lookback_days)

        # 1. Daily totals per store-SKU (sale lines only: returns and voided lines are not demand)
        stmt_sales = (
            select(
                SalesLine.store_id,
                SalesLine.product_id,
                SalesLine.txn_date.label("ds"),
                func.sum(SalesLine.qty).label("y"),
                func.sum(SalesLine.unit_price * SalesLine.qty - SalesLine.discount).label("revenue"),
            )
            .where(
                SalesLine.store_id.in_(ctx.store_ids),
                SalesLine.txn_date >= lookback_start,
                SalesLine.txn_date < ctx.run_date,
                SalesLine.is_voided.is_(False),
                SalesLine.is_return.is_(False),
                SalesLine.qty > 0,
            )
            .group_by(SalesLine.store_id, SalesLine.product_id, SalesLine.txn_date)
        )
        sales_rows = list(ctx.session.execute(stmt_sales).all())
        if not sales_rows:
            return AgentResult(status="SUCCESS", outputs={"forecasts": 0, "low_confidence": 0}, step_count=1)

        # 2. Stockout days, excluded from the demand estimate (D-30)
        stmt_stockout = select(
            InventoryDailySnapshot.store_id,
            InventoryDailySnapshot.product_id,
            InventoryDailySnapshot.snapshot_date,
        ).where(
            InventoryDailySnapshot.store_id.in_(ctx.store_ids),
            InventoryDailySnapshot.snapshot_date >= lookback_start,
            InventoryDailySnapshot.snapshot_date < ctx.run_date,
            InventoryDailySnapshot.closing_on_hand <= 0,
        )
        stockouts = {(r[0], r[1], r[2]) for r in ctx.session.execute(stmt_stockout).all()}
        series = daily_series(sales_rows, lookback_start, ctx.run_date, stockouts)

        # 3. ABC / XYZ classification: one query for the listed store-SKUs, one bulk UPDATE by primary key
        classified = ForecastTools.classify_abc_xyz(series[["unique_id", "ds", "y", "revenue"]])
        listed = {
            (store_id, product_id)
            for store_id, product_id in ctx.session.execute(
                select(StoreProduct.store_id, StoreProduct.product_id).where(
                    StoreProduct.store_id.in_(ctx.store_ids)
                )
            )
        }
        updates: list[dict[str, Any]] = []
        for row in classified.itertuples():
            store_id, product_id = (UUID(part) for part in str(row.unique_id).split(":"))
            if (store_id, product_id) in listed:
                updates.append(
                    {
                        "store_id": store_id,
                        "product_id": product_id,
                        "abc_class": str(row.abc),
                        "xyz_class": str(row.xyz),
                    }
                )
        if updates:
            ctx.session.execute(update(StoreProduct), updates)

        # 4. Baseline, then 5. model selection
        model_input = series[["unique_id", "ds", "y", "is_stockout"]]
        forecasts = ForecastTools.baseline_avg_daily(model_input, window_days=params.kpi_lookback_days)
        if params.use_model_selection:
            cv = ForecastTools.backtest_models(
                model_input,
                horizon=params.forecast_horizon_days,
                min_history_days=params.min_history_days,
                window_days=params.kpi_lookback_days,
            )
            forecasts = ForecastTools.select_best(cv, forecasts)

        stale_set = set(ctx.stale_skus)
        forecast_models: list[Forecast] = []
        low_confidence_count = 0
        methods: dict[str, int] = {}
        for row in forecasts.itertuples():
            store_id, product_id = (UUID(part) for part in str(row.unique_id).split(":"))
            in_stock_days = int(cast(Any, row.in_stock_days))
            confidence = "HIGH"
            if (store_id, product_id) in stale_set or in_stock_days < MIN_IN_STOCK_DAYS:
                confidence = "LOW"
                low_confidence_count += 1
            method = str(row.method)
            methods[method] = methods.get(method, 0) + 1
            forecast_models.append(
                Forecast(
                    run_id=ctx.run_id,
                    store_id=store_id,
                    product_id=product_id,
                    horizon_days=params.forecast_horizon_days,
                    daily_demand=float(cast(Any, row.daily_demand)),
                    method=method,
                    confidence=confidence,
                )
            )

        planning_repo.bulk_insert_forecasts(ctx.run_id, forecast_models)
        ctx.session.flush()

        return AgentResult(
            status="SUCCESS",
            outputs={
                "forecasts": len(forecast_models),
                "low_confidence": low_confidence_count,
                "methods": methods,
            },
            step_count=5,
        )
