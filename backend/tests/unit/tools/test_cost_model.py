"""CostModel — incremental costs only (spec §1, D-10, D-23)."""

from decimal import Decimal

import pytest

from app.tools.cost_model import CostModel
from app.tools.types import StoreState
from tests.unit.tools.builders import STORE_A, route, terms


def _donor(daily_demand: float) -> StoreState:
    return StoreState(store_id=STORE_A, requirement=30, available=54, daily_demand=daily_demand)


def _po_cost(
    daily_demand: float = 2,
    *,
    order_fixed_share: str = "250",
    delivery_charge_share: str = "150",
    is_perishable: bool = False,
    cap: int = 90,
) -> Decimal:
    return CostModel.po_incremental_cost(
        qty=24,
        unit_cost=Decimal("50"),
        donor=_donor(daily_demand),
        terms=terms(),
        order_fixed_share=Decimal(order_fixed_share),
        delivery_charge_share=Decimal(delivery_charge_share),
        holding_rate=Decimal("0.0005"),
        expiry_risk_pct=Decimal("0.10"),
        is_perishable=is_perishable,
        days_to_sell_cap=cap,
    )


def test_transfer_incremental_cost() -> None:
    # fixed 100 + 2 × 24 transport + 1 × 24 handling
    assert CostModel.transfer_incremental_cost(route(), 24) == Decimal("172")


def test_po_incremental_cost_components() -> None:
    # 250 order share + 150 delivery share + 24 × 50 × 0.0005 × (24 / 2 = 12 days) = 407.2
    assert _po_cost() == Decimal("407.2")


def test_po_incremental_cost_excludes_the_purchase_price() -> None:
    # 24 units × ₹50 = ₹1 200 is paid either way, so only the holding cost of the donor surplus remains.
    assert _po_cost(order_fixed_share="0", delivery_charge_share="0") == Decimal("7.2")


def test_expiry_risk_only_for_perishables() -> None:
    assert _po_cost(is_perishable=True) - _po_cost(is_perishable=False) == Decimal("120")  # 24 × 50 × 0.10


def test_days_to_sell_is_capped_and_zero_demand_uses_the_cap() -> None:
    assert _po_cost(daily_demand=0, order_fixed_share="0", delivery_charge_share="0") == Decimal(
        "54"
    )  # 90 days
    assert _po_cost(daily_demand=0.1, order_fixed_share="0", delivery_charge_share="0", cap=30) == Decimal(
        "18"
    )


@pytest.mark.parametrize(
    ("qty", "daily_demand", "cap", "expected"),
    [(24, 2, 90, "12"), (24, 0, 30, "30"), (24, 0.1, 90, "90"), (10, 3, 90, "3.333333")],
)
def test_days_to_sell(qty: int, daily_demand: float, cap: int, expected: str) -> None:
    assert CostModel.days_to_sell(qty, daily_demand, cap) == Decimal(expected)
