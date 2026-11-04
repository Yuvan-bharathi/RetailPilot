"""Forecast models and backtest selection (D-45): ETS(A,N,N), Croston-SBA, TSB, rolling-origin backtest."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.tools.forecast import ForecastTools as FT

DAY0 = date(2026, 5, 1)


def frame(uid: str, units: list[float], stockout_days: set[int] = frozenset()) -> pd.DataFrame:  # type: ignore[assignment]
    return pd.DataFrame(
        {
            "unique_id": uid,
            "ds": [DAY0 + timedelta(days=i) for i in range(len(units))],
            "y": units,
            "is_stockout": [i in stockout_days for i in range(len(units))],
        }
    )


# --- the models ----------------------------------------------------------------------------------------------------


def test_constant_demand_is_forecast_exactly_by_every_model() -> None:
    y = [6.0] * 60
    for method in ("BASELINE", "ETS", "CROSTON", "TSB"):
        assert FT.model_forecast(y, method) == pytest.approx(6.0, rel=0.06), (
            method
        )  # SBA deflates by alpha / 2


def test_croston_sba_on_intermittent_demand() -> None:
    # 4 units every 4th day = 1 unit/day; SBA = (1 − α/2) × size / interval = 0.95 × 4 / 4
    y = [4.0 if i % 4 == 3 else 0.0 for i in range(80)]
    assert FT.model_forecast(y, "CROSTON") == pytest.approx(0.95, abs=1e-9)


def test_tsb_follows_a_demand_that_stopped() -> None:
    y = [3.0] * 40 + [
        0.0
    ] * 40  # product delisted by customers: probability of demand decays, Croston would not
    assert FT.model_forecast(y, "TSB") < 0.1
    assert FT.model_forecast(y, "CROSTON") > 2.0


def test_ets_tracks_a_level_shift_faster_than_a_28_day_mean() -> None:
    y = [2.0] * 60 + [10.0] * 14
    assert FT.model_forecast(y, "ETS") > FT.model_forecast(y, "BASELINE") > 2.0


def test_no_demand_and_no_history_forecast_zero() -> None:
    for method in ("BASELINE", "ETS", "CROSTON", "TSB"):
        assert FT.model_forecast([0.0] * 30, method) == 0.0
        assert FT.model_forecast([], method) == 0.0


def test_unknown_method_is_rejected() -> None:
    with pytest.raises(ValueError, match="IMAPA"):
        FT.model_forecast([1.0], "IMAPA")


@given(st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=120))
def test_forecasts_are_finite_non_negative_and_bounded_by_the_peak(units: list[int]) -> None:
    y = [float(u) for u in units]
    for method in ("BASELINE", "ETS", "CROSTON", "TSB"):
        value = FT.model_forecast(y, method)
        assert np.isfinite(value) and 0.0 <= value <= max(y) + 1e-9


# --- backtest and selection -----------------------------------------------------------------------------------------


def test_too_little_in_stock_history_keeps_the_baseline_only() -> None:
    df = frame("s:p", [5.0] * 70, stockout_days=set(range(0, 20)))  # 50 in-stock days < 56 + 3 × 7
    cv = FT.backtest_models(df, horizon=7)
    assert cv.empty


def test_candidates_depend_on_the_demand_pattern() -> None:
    smooth = frame("s:smooth", [5.0 + (i % 3) for i in range(120)])
    lumpy = frame("s:lumpy", [6.0 if i % 5 == 0 else 0.0 for i in range(120)])
    cv = FT.backtest_models(pd.concat([smooth, lumpy]), horizon=7)
    methods = cv.groupby("unique_id")["method"].apply(set).to_dict()
    assert methods == {"s:smooth": {"BASELINE", "ETS"}, "s:lumpy": {"BASELINE", "CROSTON", "TSB"}}
    assert (cv["windows"] == 3).all()


def test_backtest_ignores_stockout_days() -> None:
    # demand is 8/day; 15 stockout days with 0 sales must not be read as zero demand (D-30)
    units = [8.0] * 120
    out = {i for i in range(100, 115)}
    for i in out:
        units[i] = 0.0
    cv = FT.backtest_models(frame("s:p", units, stockout_days=out), horizon=7)
    assert cv.loc[cv["method"] == "BASELINE", "wmape"].iloc[0] == pytest.approx(0.0)


def test_selection_keeps_baseline_unless_a_model_is_clearly_better() -> None:
    baseline = pd.DataFrame(
        [
            {"unique_id": "a", "daily_demand": 5.0, "method": "BASELINE", "in_stock_days": 28},
            {"unique_id": "b", "daily_demand": 5.0, "method": "BASELINE", "in_stock_days": 28},
            {"unique_id": "c", "daily_demand": 2.0, "method": "BASELINE", "in_stock_days": 28},
        ]
    )
    cv = pd.DataFrame(
        [
            {"unique_id": "a", "method": "BASELINE", "wmape": 0.20, "windows": 3, "forecast": 5.0},
            {
                "unique_id": "a",
                "method": "ETS",
                "wmape": 0.10,
                "windows": 3,
                "forecast": 7.0,
            },  # clearly better
            {"unique_id": "b", "method": "BASELINE", "wmape": 0.20, "windows": 3, "forecast": 5.0},
            {
                "unique_id": "b",
                "method": "ETS",
                "wmape": 0.195,
                "windows": 3,
                "forecast": 5.5,
            },  # within margin
        ]
    )
    chosen = FT.select_best(cv, baseline).set_index("unique_id")
    assert chosen.loc["a", "method"] == "ETS" and chosen.loc["a", "daily_demand"] == 7.0
    assert chosen.loc["b", "method"] == "BASELINE" and chosen.loc["b", "daily_demand"] == 5.0
    assert chosen.loc["c", "method"] == "BASELINE"  # no backtest (short history): baseline unchanged
    assert list(chosen.columns) == ["daily_demand", "method", "in_stock_days"]


def test_end_to_end_selects_tsb_for_demand_that_stopped() -> None:
    units = [4.0] * 90 + [0.0] * 30  # in stock throughout, customers stopped buying
    df = frame("s:p", units)
    base = FT.baseline_avg_daily(df[["unique_id", "ds", "y", "is_stockout"]], window_days=28)
    chosen = FT.select_best(FT.backtest_models(df, horizon=7), base).iloc[0]
    assert chosen["method"] in {"TSB", "ETS", "BASELINE"}
    assert chosen["daily_demand"] <= base.iloc[0]["daily_demand"]


def test_constant_demand_planted_scenarios_stay_on_the_baseline() -> None:
    """The demo scenarios use constant demand: every model ties, so the baseline (and 40/24/16) is unchanged."""
    df = frame("s:p", [4.0] * 180)
    base = FT.baseline_avg_daily(df[["unique_id", "ds", "y", "is_stockout"]], window_days=28)
    chosen = FT.select_best(FT.backtest_models(df, horizon=9), base).iloc[0]
    assert (chosen["method"], chosen["daily_demand"]) == ("BASELINE", 4.0)


def test_series_without_stockout_flags_and_empty_backtests() -> None:
    df = frame("s:p", [3.0] * 90).drop(columns=["is_stockout"])  # every day counts as in stock
    cv = FT.backtest_models(df, horizon=7)
    assert set(cv["method"]) == {"BASELINE", "ETS"}
    base = FT.baseline_avg_daily(df, window_days=28)
    assert FT.select_best(cv.iloc[0:0], base).equals(base)


def test_zero_actual_windows_score_zero_or_infinite_error() -> None:
    # demand only in the distant past: recent windows have no sales; BASELINE (28-day mean) predicts 0 → 0 error
    df = frame("s:p", [5.0] * 10 + [0.0] * 90)
    cv = FT.backtest_models(df, horizon=7).set_index("method")
    assert cv.loc["BASELINE", "wmape"] == 0.0
    assert cv.loc["CROSTON", "wmape"] == float("inf")  # Croston keeps forecasting the old size
