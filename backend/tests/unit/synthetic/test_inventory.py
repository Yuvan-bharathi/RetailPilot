"""The stock simulator depletes batches strictly FEFO — the same rule as FreshnessTools.at_risk_by_batch."""

from datetime import date, timedelta

import numpy as np
import pytest

from app.tools.freshness import FreshnessTools
from app.tools.types import BatchInfo
from data.synthetic.catalog import uid
from data.synthetic.inventory import Delivery, SimResult, simulate

START = date(2026, 10, 1)


def _days(n: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def _run(n_days: int, daily: int, deliveries: list[Delivery]) -> SimResult:
    return simulate(
        days=_days(n_days),
        demand=np.full(n_days, daily, dtype=np.int64),
        bulk=np.zeros(n_days, dtype=np.int64),
        shelf_life=30,
        shelf_capacity=10,
        batch_prefix="T",
        opening_qty=0,
        opening_expiry=None,
        plan=deliveries,
    )


def test_batches_are_depleted_earliest_expiry_first_not_in_arrival_order() -> None:
    # three batches arrive on day 0 in the order late, early, middle expiry
    deliveries = [
        Delivery(0, 10, expiry_override=START + timedelta(days=20)),  # T-001 latest expiry
        Delivery(0, 10, expiry_override=START + timedelta(days=10)),  # T-002 earliest expiry
        Delivery(0, 10, expiry_override=START + timedelta(days=15)),  # T-003 middle
    ]

    result = _run(n_days=3, daily=6, deliveries=deliveries)  # sells 18 of 30

    remaining = {b.batch_no: b.qty for b in result.batches}
    # FEFO: T-002 (10) fully sold, then 8 of T-003; T-001 untouched
    assert remaining == {"T-001": 10, "T-003": 2}


@pytest.mark.parametrize(
    "daily",
    [
        pytest.param(1, marks=pytest.mark.xfail(strict=True, reason="spec §1 FEFO formula; proposed D-31")),
        pytest.param(3, marks=pytest.mark.xfail(strict=True, reason="spec §1 FEFO formula; proposed D-31")),
        pytest.param(4, marks=pytest.mark.xfail(strict=True, reason="spec §1 FEFO formula; proposed D-31")),
        7,  # every batch sells in time → both agree
    ],
)
def test_simulated_write_offs_equal_fefo_at_risk_prediction(daily: int) -> None:
    """Cross-check: what the simulator actually writes off vs what FreshnessTools predicts.

    The spec §1 formula adds an earlier batch's FULL qty to qty_ahead, even the part that expires unsold, so it
    overstates the risk of later batches. Proposed D-31: qty_ahead += batch.qty − at_risk (units actually sold).
    """
    expiries = [8, 4, 12]  # days from the start, delivered out of order
    qtys = [20, 15, 25]
    deliveries = [
        Delivery(0, q, expiry_override=START + timedelta(days=e)) for q, e in zip(qtys, expiries, strict=True)
    ]

    result = _run(n_days=20, daily=daily, deliveries=deliveries)

    written_off = {batch_no: qty for _, batch_no, qty in result.write_offs}
    predicted = FreshnessTools.at_risk_by_batch(
        [
            BatchInfo(uid("t", f"T-{i:03d}"), q, START + timedelta(days=e))
            for i, (q, e) in enumerate(zip(qtys, expiries, strict=True), start=1)
        ],
        daily_demand=daily,
        run_date=START,
    )
    by_batch_no = {f"T-{i:03d}": uid("t", f"T-{i:03d}") for i in range(1, 4)}
    expected = {
        no: next(r.at_risk for r in predicted if r.batch_id == bid) for no, bid in by_batch_no.items()
    }
    assert {no: written_off.get(no, 0) for no in by_batch_no} == expected
