"""RequirementCalculator — spec §1, D-02, D-07, D-14, D-16, D-23."""

from datetime import date

import pytest

from app.tools.requirement import RequirementCalculator as RC
from app.tools.types import IncomingItem, StoreState
from tests.unit.tools.builders import STORE_A


def test_demand_window_is_lead_time_plus_review_period() -> None:
    assert RC.demand_window(lead_time_days=3, review_period_days=2) == 5


@pytest.mark.parametrize(
    ("store", "lead", "review", "expected"),
    [
        # daily demand 4, safety 2 days, display minimum 6 (business requirements §5.3 windows)
        ("A", 3, 2, 20 + 8 + 6),  # window 5
        ("B", 7, 2, 36 + 8 + 6),  # window 9
        ("C", 5, 3, 32 + 8 + 6),  # window 8
    ],
)
def test_own_requirement_uses_each_stores_own_window(
    store: str, lead: int, review: int, expected: int
) -> None:
    requirement = RC.own_requirement(
        daily_demand=4, lead_time_days=lead, review_period_days=review, safety_stock_days=2, min_display_qty=6
    )
    assert requirement == expected, store


def test_window_and_safety_are_ceiled_separately() -> None:
    # ceil(2.5 × 5) + ceil(2.5 × 1) = 13 + 3 = 16 (not ceil(2.5 × 6) = 15)
    assert RC.own_requirement(2.5, 3, 2, 1, 0) == 16


def test_float_artefacts_do_not_add_a_unit() -> None:
    assert 0.14 * 50 > 7  # 7.000000000000001 in binary floating point
    assert RC.own_requirement(0.14, 50, 0, 0, 0) == 7
    assert RC.own_requirement(0.14, 0, 0, 50, 0) == 7


def test_zero_demand_keeps_only_the_display_minimum() -> None:
    assert RC.own_requirement(0, 5, 2, 3, 6) == 6


@pytest.mark.parametrize(
    "args",
    [(-1.0, 1, 1, 1, 1), (1.0, -1, 1, 1, 1), (1.0, 1, -1, 1, 1), (1.0, 1, 1, -1, 1), (1.0, 1, 1, 1, -1)],
)
def test_own_requirement_rejects_negative_inputs(args: tuple[float, int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        RC.own_requirement(*args)


def test_available_is_shelf_plus_backroom_plus_incoming_minus_reserved() -> None:
    assert RC.available(shelf_qty=10, backroom_qty=5, incoming=3, reserved=4) == 14


def test_surplus_can_be_negative() -> None:
    assert RC.surplus(available=54, requirement=30) == 24
    assert RC.surplus(available=10, requirement=30) == -20


def test_donor_protection() -> None:
    donor = StoreState(store_id=STORE_A, requirement=30, available=54, daily_demand=3)

    assert RC.assert_donor_protected(donor, 24) is True
    assert RC.assert_donor_protected(donor, 25) is False


@pytest.mark.parametrize(
    ("available", "daily_demand", "review", "requirement", "expected"),
    [
        (20, 4, 2, 15, 3),  # projected 12 < 15 → 3
        (20, 4, 2, 12, 0),  # projected 12, not below 12 → does not qualify
        (40, 6, 3, 30, 8),  # not short today (40 ≥ 30) but falls below before the next review → 8
        (20, 4.25, 2, 12, 1),  # projected 11.5 → ceil(0.5) = 1
        (5, 0, 7, 5, 0),  # no demand → never falls
    ],
)
def test_co_replenish_qty(
    available: int, daily_demand: float, review: int, requirement: int, expected: int
) -> None:
    assert RC.co_replenish_qty(available, daily_demand, review, requirement) == expected


def test_co_replenish_qty_ignores_float_artefacts() -> None:
    # 35 − 0.14 × 50 = 28 exactly in decimal (27.999999999999996 in float) → not below a requirement of 28
    assert RC.co_replenish_qty(35, 0.14, 50, 28) == 0


@pytest.mark.parametrize(
    ("terms_lead", "product_lead", "default_lead", "expected"),
    [(3, 5, 9, 3), (None, 5, 9, 5), (None, None, 9, 9), (0, 5, 9, 0)],
)
def test_lead_time_precedence(
    terms_lead: int | None, product_lead: int | None, default_lead: int, expected: int
) -> None:
    assert RC.lead_time(terms_lead, product_lead, default_lead) == expected


def test_planning_incoming_excludes_overdue_and_adds_on_order_pending() -> None:
    run_date = date(2026, 11, 10)
    items = [
        IncomingItem(qty=10, expected_date=date(2026, 11, 7)),  # 7 + 3 grace = 10 → not overdue
        IncomingItem(qty=20, expected_date=date(2026, 11, 6)),  # 6 + 3 = 9 < 10 → overdue, excluded
        IncomingItem(qty=5, expected_date=date(2026, 11, 12)),  # future
    ]

    assert RC.planning_incoming(items, on_order_pending=4, run_date=run_date, grace_days=3) == 10 + 5 + 4


def test_store_state_derived_values() -> None:
    state = StoreState(store_id=STORE_A, requirement=30, available=54, daily_demand=3)
    idle = StoreState(store_id=STORE_A, requirement=0, available=5, daily_demand=0)

    assert state.surplus == 24
    assert state.days_of_cover == 18
    assert idle.days_of_cover == 500  # available / 0.01


# --- days of cover and stockout risk (spec §1, D-46) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("available", "daily", "risk"),
    [
        (20, 10.0, "HIGH"),  # 2 days of cover < lead 3
        (30, 10.0, "MEDIUM"),  # 3 days: not < lead 3, but < lead + review 5
        (49, 10.0, "MEDIUM"),
        (50, 10.0, "LOW"),  # exactly lead + review
        (0, 0.0, "HIGH"),  # nothing on hand and no demand: cover 0 < 3
        (1, 0.0, "LOW"),  # demand floor 0.01 → 100 days of cover
    ],
)
def test_stockout_risk_bands_follow_lead_time_and_review(available: int, daily: float, risk: str) -> None:
    assert RC.stockout_risk(available, daily, lead_time_days=3, review_period_days=2) == risk


def test_days_of_cover_uses_the_demand_floor() -> None:
    assert RC.days_of_cover(30, 10.0) == 3.0
    assert RC.days_of_cover(1, 0.0) == 100.0
