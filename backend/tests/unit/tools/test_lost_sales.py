"""LostSalesCalculator — censored demand, lost revenue vs lost profit (spec §1, D-21, D-23)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pandas as pd

from app.tools.lost_sales import LostSalesCalculator
from tests.unit.tools.builders import STORE_A

P1, P2, P3, P4, P5 = (UUID(int=0x101 + i) for i in range(5))
DAY0 = date(2026, 10, 1)


def _sales(product: UUID, units: list[int]) -> list[dict[str, object]]:
    return [
        {"store_id": STORE_A, "product_id": product, "day": DAY0 + timedelta(days=i), "units": u}
        for i, u in enumerate(units)
    ]


def _stockouts(product: UUID, day_indexes: list[int]) -> list[dict[str, object]]:
    return [
        {"store_id": STORE_A, "product_id": product, "day": DAY0 + timedelta(days=i)} for i in day_indexes
    ]


def _estimate() -> pd.DataFrame:
    daily_sales = pd.DataFrame(
        # P1: day 5 opened with stock and sold 3 before running out (censored); day 6 empty all day.
        _sales(P1, [5, 5, 0, 5, 5, 3, 0, 5, 5, 5])
        + _sales(P2, [4, 4, 4, 4, 4, 0, 0, 0, 0, 0])  # only 5 in-stock days → LOW confidence
        + _sales(P3, [2] * 10)  # never out of stock
        + _sales(P4, [1, 1, 1, 1, 1, 1, 1, 2, 0])  # sum 9 over 8 in-stock days → rate 1.125
        + _sales(P5, [0, 0, 0])  # out of stock every day
    )
    stockout_days = pd.DataFrame(
        _stockouts(P1, [5, 6])
        + _stockouts(P2, [5, 6, 7, 8, 9])
        + _stockouts(P4, [8])
        + _stockouts(P5, [0, 1, 2])
    )
    margins = pd.DataFrame(
        [
            {"product_id": P1, "selling_price": Decimal("40"), "unit_margin": Decimal("10")},
            {"product_id": P2, "selling_price": Decimal("20"), "unit_margin": Decimal("5")},
            {"product_id": P3, "selling_price": Decimal("10"), "unit_margin": Decimal("2")},
            {"product_id": P4, "selling_price": Decimal("1"), "unit_margin": Decimal("0.5")},
            {"product_id": P5, "selling_price": Decimal("9"), "unit_margin": Decimal("3")},
        ]
    )
    result = LostSalesCalculator.estimate(daily_sales, stockout_days, margins)
    return result.set_index("product_id")


def test_censored_stockout_days_are_excluded_from_the_demand_rate() -> None:
    row = _estimate().loc[P1]

    # in-stock days: 5,5,0,5,5,5,5,5 → 35 / 8 = 4.375 per day (zero-sale day included, days 5–6 excluded)
    assert row["demand_rate"] == 4.375
    assert row["stockout_days"] == 2
    assert row["in_stock_days"] == 8
    assert row["lost_units"] == 8.75


def test_lost_revenue_and_lost_profit_are_separate() -> None:
    row = _estimate().loc[P1]

    assert row["lost_revenue"] == Decimal("350.00")  # 8.75 × 40
    assert row["lost_profit"] == Decimal("87.50")  # 8.75 × 10
    assert row["confidence"] == "HIGH"


def test_fewer_than_seven_in_stock_days_is_low_confidence() -> None:
    row = _estimate().loc[P2]

    assert row["in_stock_days"] == 5
    assert row["confidence"] == "LOW"
    assert row["lost_units"] == 20  # 4 per day × 5 stockout days


def test_no_stockout_means_no_lost_sales() -> None:
    row = _estimate().loc[P3]

    assert row["lost_units"] == 0
    assert row["lost_revenue"] == Decimal("0.00")


def test_money_is_rounded_half_up_at_output() -> None:
    row = _estimate().loc[P4]

    assert row["lost_units"] == 1.125
    assert row["lost_revenue"] == Decimal("1.13")  # banker's rounding would give 1.12
    assert row["lost_profit"] == Decimal("0.56")  # 0.5625 → 0.56


def test_always_out_of_stock_has_no_demand_estimate() -> None:
    row = _estimate().loc[P5]

    assert row["demand_rate"] == 0
    assert row["lost_units"] == 0
    assert row["confidence"] == "LOW"


def test_empty_input_gives_empty_result_with_columns() -> None:
    empty = LostSalesCalculator.estimate(
        pd.DataFrame(columns=["store_id", "product_id", "day", "units"]),
        pd.DataFrame(columns=["store_id", "product_id", "day"]),
        pd.DataFrame(columns=["product_id", "selling_price", "unit_margin"]),
    )

    assert empty.empty
    assert {"lost_units", "lost_revenue", "lost_profit", "confidence"} <= set(empty.columns)
