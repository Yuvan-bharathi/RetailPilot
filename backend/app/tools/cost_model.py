"""CostModel — incremental cost of a transfer vs a purchase order (spec §1, SD-07, D-10).

Only incremental costs are compared. The purchase price of the units is never included: it is paid whichever
option is chosen. Values are unrounded; round with numeric.money() only for output (D-23).
"""

from decimal import Decimal

from app.tools.numeric import to_decimal
from app.tools.types import StoreState, SupplyTermsLike, TransferRouteLike


class CostModel:
    @staticmethod
    def transfer_incremental_cost(route: TransferRouteLike, qty: int) -> Decimal:
        """fixed trip cost + per-unit transport × qty + handling at both stores × qty."""
        return route.fixed_cost + route.per_unit_cost * qty + route.handling_cost_per_unit * qty

    @staticmethod
    def days_to_sell(qty: int, daily_demand: float, cap_days: int) -> Decimal:
        """Days the donor needs to sell `qty`, capped at `cap_days`; the cap when demand is 0 (D-10)."""
        if daily_demand <= 0:
            return Decimal(cap_days)
        return min(to_decimal(qty / daily_demand), Decimal(cap_days))

    @staticmethod
    def po_incremental_cost(
        qty: int,
        unit_cost: Decimal,
        donor: StoreState,
        terms: SupplyTermsLike,
        order_fixed_share: Decimal,
        delivery_charge_share: Decimal,
        holding_rate: Decimal,
        expiry_risk_pct: Decimal,
        is_perishable: bool,
        days_to_sell_cap: int,
    ) -> Decimal:
        """Extra cost of buying instead of transferring `qty` from `donor`.

        order share + delivery share (both 0 when the PO happens anyway, D-17)
        + holding cost of the donor's surplus left unsold + expected expiry loss (perishables only).
        `terms` identifies the supplier serving the short store; its delivery charge enters through
        `delivery_charge_share`, which the caller sets to 0 or `terms.delivery_charge`.
        """
        del terms  # part of the spec signature; the share arguments carry its charges
        days = CostModel.days_to_sell(qty, donor.daily_demand, days_to_sell_cap)
        holding = qty * unit_cost * holding_rate * days
        expiry = qty * unit_cost * expiry_risk_pct if is_perishable else Decimal(0)
        return order_fixed_share + delivery_charge_share + holding + expiry
