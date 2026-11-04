"""ForecastTools — ABC-XYZ classification, the baseline forecast (SD-04, D-22, D-30) and model selection (D-45).

Model selection (D-45) replaces the spec's statsforecast extension (statsforecast requires pandas < 3): ETS(A,N,N)
(simple exponential smoothing) for smooth demand, Croston with the Syntetos-Boylan correction and TSB for
intermittent demand, chosen per store-SKU by a rolling-origin backtest against the baseline. Pure numpy, no I/O.
Calendar uplift remains a later extension.
"""

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

ABC_XYZ_COLUMNS = ["unique_id", "abc", "xyz", "cv", "adi"]
BASELINE_COLUMNS = ["unique_id", "daily_demand", "method", "in_stock_days"]
CV_COLUMNS = ["unique_id", "method", "wmape", "windows", "forecast"]

METHODS = ("BASELINE", "ETS", "CROSTON", "TSB")
SMOOTH_CANDIDATES = ("BASELINE", "ETS")
INTERMITTENT_CANDIDATES = ("BASELINE", "CROSTON", "TSB")
ETS_ALPHAS = (0.05, 0.1, 0.2, 0.3, 0.5)
CROSTON_ALPHA = 0.1
TSB_ALPHA = 0.1
TSB_BETA = 0.1


def _ses(y: np.ndarray, alpha: float) -> tuple[float, float]:
    """Final level and in-sample one-step-ahead squared error of simple exponential smoothing."""
    level, sse = float(y[0]), 0.0
    for value in y[1:]:
        error = float(value) - level
        sse += error * error
        level += alpha * error
    return level, sse


def _ets(y: np.ndarray) -> float:
    """ETS(A,N,N): the smoothing constant with the lowest in-sample one-step error (ties → smaller alpha)."""
    best_alpha = min(ETS_ALPHAS, key=lambda a: (_ses(y, a)[1], a))
    return _ses(y, best_alpha)[0]


def _croston_sba(y: np.ndarray, alpha: float = CROSTON_ALPHA) -> float:
    """Croston with the Syntetos-Boylan approximation: (1 − α/2) × demand size / interval."""
    first = int(np.flatnonzero(y > 0)[0])  # model_forecast guarantees at least one demand day
    size, interval, since = float(y[first]), float(first + 1), 0
    for value in y[first + 1 :]:
        since += 1
        if value > 0:
            size += alpha * (float(value) - size)
            interval += alpha * (since - interval)
            since = 0
    return (1 - alpha / 2) * size / interval


def _tsb(y: np.ndarray, alpha: float = TSB_ALPHA, beta: float = TSB_BETA) -> float:
    """Teunter-Syntetos-Babai: the demand probability is updated every day, so demand that stops decays to 0."""
    probability, size = (
        float((y > 0).mean()),
        float(y[y > 0].mean()),
    )  # at least one demand day (model_forecast)
    for value in y:
        if value > 0:
            probability += beta * (1 - probability)
            size += alpha * (float(value) - size)
        else:
            probability -= beta * probability
    return probability * size


def _store_of(unique_id: str) -> str:
    return unique_id.split(":", 1)[0]


class ForecastTools:
    @staticmethod
    def classify_abc_xyz(
        series: pd.DataFrame,
        value_col: str = "revenue",
        a_cut: float = 0.8,
        b_cut: float = 0.95,
        x_cv: float = 0.5,
        y_cv: float = 1.0,
    ) -> pd.DataFrame:
        """series: [unique_id ("store:product"), ds, y, <value_col>], zero-filled days.

        ABC per store: an item is A while the cumulative value share before it is < a_cut, B while < b_cut, else C
        (stores with no value: all C). XYZ: cv = std(y) / mean(y) (population std; ∞ when mean is 0) — X < x_cv,
        Y < y_cv, else Z. ADI = days / days with sales (∞ when none).
        """
        stats = series.groupby("unique_id", sort=True).agg(
            value=(value_col, "sum"),
            mean=("y", "mean"),
            std=("y", lambda y: float(y.std(ddof=0))),
            days=("y", "size"),
            sale_days=("y", lambda y: int((y > 0).sum())),
        )

        abc: dict[str, str] = {}
        stats["store"] = [_store_of(str(uid)) for uid in stats.index]
        for _, group in stats.groupby("store", sort=True):
            total = float(group["value"].sum())
            ordered = group.sort_values("value", ascending=False, kind="stable")
            before = 0.0
            for uid, value in ordered["value"].items():
                share_before = before / total if total > 0 else 1.0
                abc[str(uid)] = "A" if share_before < a_cut else "B" if share_before < b_cut else "C"
                before += float(value)

        rows: list[dict[str, object]] = []
        for uid, row in stats.iterrows():
            mean = float(row["mean"])
            cv = float(row["std"]) / mean if mean > 0 else math.inf
            xyz = "X" if cv < x_cv else "Y" if cv < y_cv else "Z"
            sale_days = int(row["sale_days"])
            adi = int(row["days"]) / sale_days if sale_days else math.inf
            rows.append({"unique_id": uid, "abc": abc[str(uid)], "xyz": xyz, "cv": cv, "adi": adi})
        return pd.DataFrame(rows, columns=ABC_XYZ_COLUMNS)

    @staticmethod
    def baseline_avg_daily(df: pd.DataFrame, window_days: int = 28) -> pd.DataFrame:
        """Mean daily units over the in-stock days of each series' last `window_days` days (D-30).

        df: [unique_id, ds, y] zero-filled, with an optional boolean `is_stockout` column marking stockout days
        (closing on-hand = 0, including censored days that opened with stock — D-21). Stockout days are excluded
        so they do not pull the forecast down; with no in-stock day in the window the demand is 0.0.
        Without `is_stockout` every day counts as in stock. method = BASELINE.
        """
        rows: list[dict[str, object]] = []
        for uid, group in df.groupby("unique_id", sort=True):
            dates = pd.to_datetime(group["ds"])
            in_window = dates > dates.max() - pd.Timedelta(days=window_days)
            if "is_stockout" in group.columns:
                in_window &= ~group["is_stockout"].astype(bool)
            window = group.loc[in_window, "y"]
            demand = float(window.mean()) if len(window) else 0.0
            rows.append(
                {"unique_id": uid, "daily_demand": demand, "method": "BASELINE", "in_stock_days": len(window)}
            )
        return pd.DataFrame(rows, columns=BASELINE_COLUMNS)

    @staticmethod
    def model_forecast(y: Sequence[float], method: str, window_days: int = 28) -> float:
        """Flat daily-demand forecast of one in-stock series (oldest first) with `method` (D-45)."""
        if method not in METHODS:
            raise ValueError(f"unknown forecast method {method!r}; expected one of {METHODS}")
        values = np.asarray(y, dtype=float)
        if values.size == 0 or not (values > 0).any():
            return 0.0
        if method == "BASELINE":
            return float(values[-window_days:].mean())
        if method == "ETS":
            return max(0.0, _ets(values))
        if method == "CROSTON":
            return _croston_sba(values)
        return _tsb(values)

    @staticmethod
    def backtest_models(
        df: pd.DataFrame,
        horizon: int,
        n_windows: int = 3,
        min_history_days: int = 56,
        adi_threshold: float = 1.32,
        window_days: int = 28,
    ) -> pd.DataFrame:
        """Rolling-origin backtest of the candidate models per series (D-45).

        df: [unique_id, ds, y] zero-filled, optional `is_stockout` (stockout days are dropped — censored demand,
        D-30). A series is tested only with at least `min_history_days + n_windows × horizon` in-stock days.
        Candidates by ADI of the in-stock series: < `adi_threshold` → BASELINE, ETS; else BASELINE, CROSTON, TSB.
        Error = WMAPE of the horizon TOTAL (what the requirement uses): Σ|forecast × h − actual sum| / Σ actual sum
        over the windows. `forecast` = the model refitted on the whole in-stock series.
        Returns [unique_id, method, wmape, windows, forecast]; empty when no series qualifies.
        """
        rows: list[dict[str, object]] = []
        for uid, group in df.sort_values("ds", kind="stable").groupby("unique_id", sort=True):
            if "is_stockout" in group.columns:
                group = group[~group["is_stockout"].astype(bool)]
            y = group["y"].to_numpy(dtype=float)
            if y.size < min_history_days + n_windows * horizon:
                continue
            sale_days = int((y > 0).sum())
            adi = y.size / sale_days if sale_days else math.inf
            candidates = SMOOTH_CANDIDATES if adi < adi_threshold else INTERMITTENT_CANDIDATES
            for method in candidates:
                abs_error = actual_total = 0.0
                for k in range(n_windows, 0, -1):
                    cut = y.size - k * horizon
                    predicted = ForecastTools.model_forecast(y[:cut].tolist(), method, window_days) * horizon
                    actual = float(y[cut : cut + horizon].sum())
                    abs_error += abs(predicted - actual)
                    actual_total += actual
                no_demand_error = 0.0 if abs_error == 0 else math.inf
                wmape = abs_error / actual_total if actual_total > 0 else no_demand_error
                rows.append(
                    {
                        "unique_id": uid,
                        "method": method,
                        "wmape": wmape,
                        "windows": n_windows,
                        "forecast": ForecastTools.model_forecast(y.tolist(), method, window_days),
                    }
                )
        return pd.DataFrame(rows, columns=CV_COLUMNS)

    @staticmethod
    def select_best(
        cv_results: pd.DataFrame, baseline: pd.DataFrame, min_improvement: float = 0.05
    ) -> pd.DataFrame:
        """Per series: the backtest winner if it beats the baseline's WMAPE by more than `min_improvement`
        (relative); otherwise — and for series without a backtest — the baseline, unchanged (D-30).
        Returns [unique_id, daily_demand, method, in_stock_days] in the baseline's order.
        """
        chosen = baseline[BASELINE_COLUMNS].reset_index(drop=True).copy()
        if cv_results.empty:
            return chosen
        groups = {str(uid): group for uid, group in cv_results.groupby("unique_id", sort=False)}
        for i in range(len(chosen)):
            group = groups.get(str(chosen.at[i, "unique_id"]))
            if group is None:
                continue
            base = group.loc[group["method"] == "BASELINE", "wmape"]
            best = group.sort_values(["wmape", "method"], kind="stable").iloc[0]
            beats_baseline = base.empty or float(best["wmape"]) < float(base.iloc[0]) * (1 - min_improvement)
            if best["method"] != "BASELINE" and beats_baseline:
                chosen.at[i, "daily_demand"] = float(best["forecast"])
                chosen.at[i, "method"] = str(best["method"])
        return chosen
