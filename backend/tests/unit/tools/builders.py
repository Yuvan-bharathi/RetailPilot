"""Fixed ids and builders shared by the tool tests."""

from decimal import Decimal
from uuid import UUID

from app.tools.types import CostInputs, Route, StoreSupplyTerms

STORE_A = UUID(int=0xA)
STORE_B = UUID(int=0xB)
STORE_C = UUID(int=0xC)
PRODUCT = UUID(int=0x100)
SUPPLIER = UUID(int=0x5)


def terms(
    lead_time_days: int = 5,
    delivery_charge: str = "150",
    unit_cost: str = "50",
    supplier_id: UUID = SUPPLIER,
) -> StoreSupplyTerms:
    return StoreSupplyTerms(
        supplier_id=supplier_id,
        lead_time_days=lead_time_days,
        delivery_charge=Decimal(delivery_charge),
        unit_cost=Decimal(unit_cost),
    )


def route(fixed: str = "100", per_unit: str = "2", handling: str = "1", transit_days: int = 1) -> Route:
    return Route(
        fixed_cost=Decimal(fixed),
        per_unit_cost=Decimal(per_unit),
        handling_cost_per_unit=Decimal(handling),
        transit_days=transit_days,
    )


def all_routes(r: Route | None = None) -> dict[tuple[UUID, UUID], Route]:
    stores = (STORE_A, STORE_B, STORE_C)
    return {(a, b): r or route() for a in stores for b in stores if a != b}


def cost_inputs(
    lead_time_days: int = 5,
    planned: frozenset[tuple[UUID, UUID]] = frozenset(),
    is_perishable: bool = False,
) -> CostInputs:
    t = terms(lead_time_days=lead_time_days)
    return CostInputs(
        terms_by_store={STORE_A: t, STORE_B: t, STORE_C: t},
        order_fixed_cost=Decimal("250"),
        holding_cost_rate_per_day=Decimal("0.0005"),
        expiry_risk_pct=Decimal("0.10"),
        is_perishable=is_perishable,
        days_to_sell_cap=90,
        planned_supplier_stores=planned,
    )
