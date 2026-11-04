"""The 28-day replay computes its figures (no constants) and the agent's daily series are daily totals."""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from app.agents.forecasting import daily_series
from data.synthetic.reader import Dataset
from scripts.replay_evaluation import evaluate, metrics, render


@pytest.fixture(scope="module")
def evaluation(dataset: Dataset):  # type: ignore[no-untyped-def]
    return evaluate(dataset, "small", 42)


def test_metrics_are_computed_from_rows() -> None:
    rows = pd.DataFrame(
        {
            "forecast": [10.0, 30.0],
            "actual": [20.0, 20.0],
            "pred_need": [5, 0],
            "actual_need": [5, 4],
        }
    )
    m = metrics(rows)
    assert m["wmape"] == pytest.approx(20 / 40)  # |10−20| + |30−20| over 40
    assert m["bias"] == pytest.approx(0.0)
    assert (m["accuracy"], m["precision"], m["recall"]) == (0.5, 1.0, 0.5)
    assert m["need_wmape"] == pytest.approx(4 / 9)


def test_replay_uses_four_weekly_origins_and_both_variants(evaluation) -> None:  # type: ignore[no-untyped-def]
    assert len(evaluation.origins) == 4
    assert evaluation.origins[1] - evaluation.origins[0] == timedelta(days=7)
    counts = evaluation.rows.groupby("variant").size()
    assert counts["BASELINE"] == counts["MODEL_SELECTION"] > 100


def test_planted_constant_demand_is_forecast_exactly(evaluation, dataset: Dataset) -> None:  # type: ignore[no-untyped-def]
    """Scenario 1 (rice, constant demand) — the forecast window total equals what was sold."""
    product = dataset.manifest["scenarios"]["1"]["product_id"]
    rows = evaluation.rows[evaluation.rows["unique_id"].str.endswith(product)]
    assert not rows.empty
    assert (rows["forecast"] - rows["actual"]).abs().max() == pytest.approx(0.0)


def test_report_contains_the_computed_numbers(evaluation) -> None:  # type: ignore[no-untyped-def]
    text = render(evaluation)
    wmape = metrics(evaluation.rows[evaluation.rows["variant"] == "BASELINE"])["wmape"]
    assert f"{wmape * 100:.1f}%" in text
    assert "synthetic" in text


def test_agent_series_are_daily_totals_zero_filled_with_stockouts() -> None:
    """Regression: the agent once averaged bill LINES (≈1 unit) instead of daily totals, over sale days only."""
    store, product = uuid4(), uuid4()
    day0 = date(2026, 10, 1)
    rows = [
        SimpleNamespace(
            store_id=store, product_id=product, ds=day0, y=10, revenue=100
        ),  # daily total (10 lines)
        SimpleNamespace(store_id=store, product_id=product, ds=day0 + timedelta(days=3), y=6, revenue=60),
    ]
    frame = daily_series(rows, day0, day0 + timedelta(days=5), {(store, product, day0 + timedelta(days=2))})
    assert list(frame["y"]) == [10.0, 0.0, 0.0, 6.0, 0.0]
    assert list(frame["is_stockout"]) == [False, False, True, False, False]
    assert frame["unique_id"].nunique() == 1
