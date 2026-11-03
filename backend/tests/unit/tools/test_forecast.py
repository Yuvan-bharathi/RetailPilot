"""ForecastTools — ABC-XYZ per store, ADI, baseline average (SD-04, D-22)."""

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from app.tools.forecast import ForecastTools

DAY0 = date(2026, 9, 1)


def _series(unique_id: str, units: list[float], price: float = 1.0) -> list[dict[str, object]]:
    return [
        {"unique_id": unique_id, "ds": DAY0 + timedelta(days=i), "y": u, "revenue": u * price}
        for i, u in enumerate(units)
    ]


def _classes() -> pd.DataFrame:
    rows = (
        # store A — revenue totals 700 / 200 / 60 / 40 over 4 days
        _series("A:p1", [175, 175, 175, 175])
        + _series("A:p2", [50, 50, 50, 50])
        + _series("A:p3", [15, 15, 15, 15])
        + _series("A:p4", [10, 10, 10, 10])
        # store B — on its own, so its single product is A even though it is tiny
        + _series("B:p4", [1, 1, 1, 1])
        # XYZ / ADI shapes (store C)
        + _series("C:steady", [4, 6, 4, 6])  # cv 0.2 → X
        + _series("C:wavy", [2, 8, 2, 8])  # cv 0.6 → Y
        + _series("C:lumpy", [0, 10, 0, 10])  # cv 1.0 → Z ; ADI 4/2 = 2
        + _series("C:dead", [0, 0, 0, 0])  # no sales → Z, ADI ∞
    )
    return ForecastTools.classify_abc_xyz(pd.DataFrame(rows)).set_index("unique_id")


@pytest.mark.parametrize(
    ("uid", "abc"),
    [("A:p1", "A"), ("A:p2", "A"), ("A:p3", "B"), ("A:p4", "C"), ("B:p4", "A")],
)
def test_abc_is_per_store_by_cumulative_revenue_share(uid: str, abc: str) -> None:
    assert _classes().loc[uid, "abc"] == abc


@pytest.mark.parametrize(
    ("uid", "xyz", "cv"),
    [("C:steady", "X", 0.2), ("C:wavy", "Y", 0.6), ("C:lumpy", "Z", 1.0), ("A:p1", "X", 0.0)],
)
def test_xyz_by_coefficient_of_variation(uid: str, xyz: str, cv: float) -> None:
    classes = _classes()
    assert classes.loc[uid, "xyz"] == xyz
    assert classes.loc[uid, "cv"] == pytest.approx(cv)


def test_adi_and_no_sales() -> None:
    classes = _classes()

    assert classes.loc["C:lumpy", "adi"] == 2.0
    assert classes.loc["C:steady", "adi"] == 1.0
    assert classes.loc["C:dead", "xyz"] == "Z"
    assert math.isinf(classes.loc["C:dead", "adi"])
    assert math.isinf(classes.loc["C:dead", "cv"])


def test_store_with_zero_revenue_is_all_c() -> None:
    classes = ForecastTools.classify_abc_xyz(pd.DataFrame(_series("D:p1", [0, 0]) + _series("D:p2", [0, 0])))

    assert set(classes["abc"]) == {"C"}


def test_baseline_avg_daily_uses_the_last_window_days() -> None:
    long_units = [100.0] * 7 + [2.0] * 28  # older spike outside the 28-day window
    short_units = [3.0, 0.0, 3.0, 0.0]  # new product with 4 days of history
    df = pd.DataFrame(_series("A:long", long_units) + _series("A:new", short_units))

    baseline = ForecastTools.baseline_avg_daily(df, window_days=28).set_index("unique_id")

    assert baseline.loc["A:long", "daily_demand"] == 2.0
    assert baseline.loc["A:new", "daily_demand"] == 1.5
    assert set(baseline["method"]) == {"BASELINE"}
    assert baseline.loc["A:long", "in_stock_days"] == 28  # no is_stockout column → every day in stock


def test_baseline_excludes_stockout_and_censored_days() -> None:
    # D-30: 26 normal days of 4 units; one censored day (opened with stock, sold 2, closed at 0) and one day
    # out of stock all day. Both are stockout days and are excluded → 4.0 (not 106 / 28 = 3.79).
    units = [4.0] * 26 + [2.0, 0.0]
    rows = _series("A:p", units)
    for row in rows[-2:]:
        row["is_stockout"] = True
    for row in rows[:-2]:
        row["is_stockout"] = False

    baseline = ForecastTools.baseline_avg_daily(pd.DataFrame(rows), window_days=28).set_index("unique_id")

    assert baseline.loc["A:p", "daily_demand"] == 4.0
    assert baseline.loc["A:p", "in_stock_days"] == 26


def test_baseline_with_no_in_stock_day_in_the_window_is_zero() -> None:
    rows = _series("A:p", [5.0] * 10 + [0.0] * 3)
    for i, row in enumerate(rows):
        row["is_stockout"] = i >= 10

    baseline = ForecastTools.baseline_avg_daily(pd.DataFrame(rows), window_days=3).set_index("unique_id")

    assert baseline.loc["A:p", "daily_demand"] == 0.0
    assert baseline.loc["A:p", "in_stock_days"] == 0


def test_baseline_avg_daily_empty_input() -> None:
    empty = ForecastTools.baseline_avg_daily(pd.DataFrame(columns=["unique_id", "ds", "y"]))

    assert empty.empty
    assert list(empty.columns) == ["unique_id", "daily_demand", "method", "in_stock_days"]
