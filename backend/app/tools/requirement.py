"""RequirementCalculator — own requirement, availability and surplus (spec §1; SD-06, SD-12, SD-15)."""

from collections.abc import Iterable
from datetime import date, timedelta

from app.tools.numeric import DEMAND_DECIMALS, ceil6
from app.tools.types import IncomingItem, StoreState


class RequirementCalculator:
    """Pure calculations; every method is a staticmethod."""

    @staticmethod
    def demand_window(lead_time_days: int, review_period_days: int) -> int:
        """Days until the next delivery: lead time of the store's supplier + review period."""
        return lead_time_days + review_period_days

    @staticmethod
    def own_requirement(
        daily_demand: float,
        lead_time_days: int,
        review_period_days: int,
        safety_stock_days: int,
        min_display_qty: int,
    ) -> int:
        """ceil(d × (lead + review)) + ceil(d × safety) + min display (D-23: rounded to 6 decimals first)."""
        if min(daily_demand, lead_time_days, review_period_days, safety_stock_days, min_display_qty) < 0:
            raise ValueError("own_requirement inputs must be non-negative")
        window = RequirementCalculator.demand_window(lead_time_days, review_period_days)
        return ceil6(daily_demand * window) + ceil6(daily_demand * safety_stock_days) + min_display_qty

    @staticmethod
    def available(shelf_qty: int, backroom_qty: int, incoming: int, reserved: int) -> int:
        """shelf + backroom + incoming − reserved."""
        return shelf_qty + backroom_qty + incoming - reserved

    @staticmethod
    def surplus(available: int, requirement: int) -> int:
        """available − requirement; ≤ 0 means the store is not a donor."""
        return available - requirement

    @staticmethod
    def assert_donor_protected(donor: StoreState, qty: int) -> bool:
        """True when the donor still holds at least its own requirement after giving `qty`."""
        return donor.available - qty >= donor.requirement

    @staticmethod
    def co_replenish_qty(
        available: int, daily_demand: float, review_period_days: int, requirement: int
    ) -> int:
        """D-02: qty to add for a complement, or 0 if it does not fall below its requirement before the next review."""
        projected = round(available - daily_demand * review_period_days, DEMAND_DECIMALS)
        if projected >= requirement:
            return 0
        return max(1, ceil6(requirement - projected))

    @staticmethod
    def lead_time(terms_lead: int | None, product_lead: int | None, default_lead: int) -> int:
        """D-07 precedence: SupplierStoreTerms → SupplierProduct → Supplier.default_lead_time_days."""
        if terms_lead is not None:
            return terms_lead
        if product_lead is not None:
            return product_lead
        return default_lead

    @staticmethod
    def planning_incoming(
        incoming_items: Iterable[IncomingItem], on_order_pending: int, run_date: date, grace_days: int
    ) -> int:
        """Incoming used by the nightly run (D-14, D-16): non-overdue incoming + on-order (pending) quantity.

        An item is overdue when expected_date + grace_days < run_date; overdue stock is not counted.
        """
        grace = timedelta(days=grace_days)
        on_time = sum(item.qty for item in incoming_items if item.expected_date + grace >= run_date)
        return on_time + on_order_pending
