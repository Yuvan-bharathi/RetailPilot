"""ForecastTools — ABC-XYZ classification and the baseline forecast (SD-04, D-22).

Statsforecast models and calendar uplift are later extensions and are not implemented here.
"""

import math

import pandas as pd

ABC_XYZ_COLUMNS = ["unique_id", "abc", "xyz", "cv", "adi"]
BASELINE_COLUMNS = ["unique_id", "daily_demand", "method"]


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
        """Mean daily units over each series' last `window_days` days (zero-filled input). method = BASELINE."""
        rows: list[dict[str, object]] = []
        for uid, group in df.groupby("unique_id", sort=True):
            dates = pd.to_datetime(group["ds"])
            window = group.loc[dates > dates.max() - pd.Timedelta(days=window_days), "y"]
            rows.append({"unique_id": uid, "daily_demand": float(window.mean()), "method": "BASELINE"})
        return pd.DataFrame(rows, columns=BASELINE_COLUMNS)
