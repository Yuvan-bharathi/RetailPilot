"""FreshnessTools.at_risk_by_batch — FEFO at-risk quantity (spec §1, D-20, D-23)."""

from datetime import date, timedelta
from uuid import UUID

from app.tools.freshness import FreshnessTools
from app.tools.types import BatchInfo

RUN = date(2026, 11, 3)
B1, B2, B3 = (UUID(int=0x601 + i) for i in range(3))


def _batch(batch_id: UUID, qty: int, days: int) -> BatchInfo:
    return BatchInfo(batch_id=batch_id, qty=qty, expiry_date=RUN + timedelta(days=days))


def test_fefo_earliest_expiry_sells_first() -> None:
    # given out of order: B2 expires later than B1
    risks = FreshnessTools.at_risk_by_batch(
        [_batch(B2, 20, 5), _batch(B1, 10, 3)], daily_demand=4, run_date=RUN
    )

    assert [(r.batch_id, r.days_left, r.sellable, r.at_risk) for r in risks] == [
        (B1, 3, 12, 0),  # 4 × 3 = 12 ≥ 10
        (B2, 5, 10, 10),  # 4 × 5 − 10 ahead = 10 → 10 of 20 at risk
    ]


def test_expired_batch_is_fully_at_risk() -> None:
    risks = FreshnessTools.at_risk_by_batch([_batch(B3, 7, 0)], daily_demand=5, run_date=RUN)

    assert (risks[0].sellable, risks[0].at_risk) == (0, 7)


def test_no_demand_puts_everything_at_risk() -> None:
    risks = FreshnessTools.at_risk_by_batch([_batch(B1, 4, 10)], daily_demand=0, run_date=RUN)

    assert risks[0].at_risk == 4


def test_float_artefacts_do_not_lose_a_unit() -> None:
    # 0.58 × 50 = 28.999999999999996 in float → sellable must be 29, so a batch of 29 is not at risk
    risks = FreshnessTools.at_risk_by_batch([_batch(B1, 29, 50)], daily_demand=0.58, run_date=RUN)

    assert risks[0].at_risk == 0


def test_same_expiry_ordered_by_batch_id() -> None:
    risks = FreshnessTools.at_risk_by_batch(
        [_batch(B2, 5, 2), _batch(B1, 5, 2)], daily_demand=3, run_date=RUN
    )

    assert [r.batch_id for r in risks] == [B1, B2]
    assert [r.at_risk for r in risks] == [0, 4]  # 6 sellable: B1 takes 5, B2 gets 1
