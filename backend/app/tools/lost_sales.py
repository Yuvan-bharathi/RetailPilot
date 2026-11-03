"""LostSalesCalculator — lost units, lost revenue and lost profit as separate KPIs (spec §1, SD-03, D-21)."""

from decimal import Decimal
from typing import Any

import pandas as pd

from app.tools.numeric import DEMAND_DECIMALS, money, to_decimal

MIN_IN_STOCK_DAYS = 7
OUTPUT_COLUMNS = [
    "store_id",
    "product_id",
    "demand_rate",
    "in_stock_days",
    "stockout_days",
    "lost_units",
    "lost_revenue",
    "lost_profit",
    "confidence",
]


class LostSalesCalculator:
    @staticmethod
    def estimate(
        daily_sales: pd.DataFrame, stockout_days: pd.DataFrame, margins: pd.DataFrame
    ) -> pd.DataFrame:
        """Estimate sales lost to stockouts per store-product.

        daily_sales:   [store_id, product_id, day, units] — one row per day in the window (zero-filled)
        stockout_days: [store_id, product_id, day]        — days with closing_on_hand = 0 (incl. censored days)
        margins:       [product_id, selling_price, unit_margin] (Decimal)

        demand_rate = mean units over in-stock days (stockout days excluded, zero-sale days included);
        lost_units = demand_rate × stockout days; confidence LOW if fewer than 7 in-stock days.
        """
        keys = ["store_id", "product_id", "day"]
        out_days = stockout_days[keys].drop_duplicates()
        merged = daily_sales.merge(out_days.assign(_out=True), on=keys, how="outer")
        merged["_out"] = merged["_out"].astype("boolean").fillna(False).astype(bool)
        merged["units"] = merged["units"].astype("float64").fillna(0.0)

        price: dict[Any, tuple[Any, Any]] = {
            row.product_id: (row.selling_price, row.unit_margin) for row in margins.itertuples()
        }
        rows: list[dict[str, object]] = []
        groups: Any = merged.groupby(["store_id", "product_id"], sort=True)
        for (store_id, product_id), group in groups:
            in_stock = group.loc[~group["_out"], "units"]
            n_in_stock = len(in_stock)
            n_out = int(group["_out"].sum())
            rate = round(float(in_stock.mean()), DEMAND_DECIMALS) if n_in_stock else 0.0
            lost_units = round(rate * n_out, DEMAND_DECIMALS)
            selling_price, unit_margin = price.get(product_id, (Decimal(0), Decimal(0)))
            units = to_decimal(lost_units)
            rows.append(
                {
                    "store_id": store_id,
                    "product_id": product_id,
                    "demand_rate": rate,
                    "in_stock_days": n_in_stock,
                    "stockout_days": n_out,
                    "lost_units": lost_units,
                    "lost_revenue": money(units * Decimal(selling_price)),
                    "lost_profit": money(units * Decimal(unit_margin)),
                    "confidence": "LOW" if n_in_stock < MIN_IN_STOCK_DAYS else "HIGH",
                }
            )
        return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
