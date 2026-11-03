"""TransferDecisionEngine — transfer surplus between own stores or buy (SD-07, SD-08; D-04, D-10, D-17, D-24).

Only genuine surplus moves; a donor is never taken below its own requirement; if no store has surplus a PO is
raised; partial surplus gives a transfer plus a PO for the remainder. All orderings are deterministic.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.tools.cost_model import CostModel
from app.tools.numeric import floor6, money
from app.tools.requirement import RequirementCalculator
from app.tools.types import (
    CostInputs,
    NeedReason,
    PONeed,
    Priority,
    StoreState,
    SupplyTermsLike,
    TransferPlan,
    TransferProposal,
    TransferRouteLike,
)

RouteMap = Mapping[tuple[UUID, UUID], TransferRouteLike]


@dataclass(slots=True)
class _Donor:
    """Mutable working copy of a donor's state while one product is being decided."""

    state: StoreState
    given: int = 0

    @property
    def current(self) -> StoreState:
        return StoreState(
            store_id=self.state.store_id,
            requirement=self.state.requirement,
            available=self.state.available - self.given,
            daily_demand=self.state.daily_demand,
            review_period_days=self.state.review_period_days,
        )


def _urgency_key(state: StoreState) -> tuple[float, UUID]:
    return (state.days_of_cover, state.store_id)


class TransferDecisionEngine:
    @staticmethod
    def _priority(state: StoreState, lead_time_days: int) -> Priority:
        """HIGH when the store runs out before a supplier delivery could arrive."""
        return "HIGH" if state.days_of_cover < lead_time_days else "NORMAL"

    @staticmethod
    def decide(
        product_id: UUID,
        states: Sequence[StoreState],
        routes: RouteMap,
        cost_inputs: CostInputs,
    ) -> TransferPlan:
        """Decide transfers and PO needs for one product across the stores in `states` (SD-07)."""
        short_stores = sorted((s for s in states if s.available < s.requirement), key=_urgency_key)
        if not short_stores:
            return TransferPlan()
        donors: dict[UUID, _Donor] = {s.store_id: _Donor(s) for s in states if s.surplus > 0}

        transfers: list[TransferProposal] = []
        po_needs: list[PONeed] = []
        for short in short_stores:
            initial_need = short.requirement - short.available
            need = initial_need
            terms = cost_inputs.terms_by_store[short.store_id]
            if not donors:
                po_needs.append(
                    _po_need(product_id, short, need, terms, "NO_SURPLUS_IN_ANY_STORE", initial_need, 0)
                )
                continue

            transferred = 0
            for donor_id in _candidates(donors, short.store_id, routes):
                if need <= 0:
                    break
                route = routes.get((donor_id, short.store_id))
                if route is None:
                    continue  # no transfer route between these stores
                donor = donors[donor_id]
                donor_now = donor.current
                qty = min(donor_now.surplus, need)
                t_cost = CostModel.transfer_incremental_cost(route, qty)
                p_cost = _po_cost(qty, donor_now, terms, short.store_id, cost_inputs)
                if not (t_cost < p_cost and route.transit_days <= terms.lead_time_days):
                    continue  # transfer costlier or slower than a PO
                # SD-07 donor protection. qty ≤ surplus guarantees it; the assert documents the invariant.
                assert RequirementCalculator.assert_donor_protected(donor_now, qty)
                transfers.append(
                    TransferProposal(
                        from_store=donor_id,
                        to_store=short.store_id,
                        product_id=product_id,
                        qty=qty,
                        transfer_cost=money(t_cost),
                        po_cost_avoided=money(p_cost),
                        transit_days=route.transit_days,
                        evidence={
                            "donor_surplus": donor_now.surplus,
                            "donor_requirement": donor_now.requirement,
                            "donor_available": donor_now.available,
                            "need": initial_need,
                            "transfer_cost": str(money(t_cost)),
                            "po_incremental_cost": str(money(p_cost)),
                            "transit_days": route.transit_days,
                            "supplier_lead_time_days": terms.lead_time_days,
                        },
                    )
                )
                donor.given += qty
                need -= qty
                transferred += qty
                if donor.current.surplus == 0:
                    del donors[donor_id]

            if need > 0:
                reason: NeedReason = "PARTIAL_SURPLUS" if transferred else "TRANSFER_NOT_VIABLE"
                po_needs.append(_po_need(product_id, short, need, terms, reason, initial_need, transferred))

        return TransferPlan(transfers=tuple(transfers), po_needs=tuple(po_needs))

    @staticmethod
    def mark_po_pairs(
        states_by_product: Mapping[UUID, Sequence[StoreState]],
        terms: Mapping[tuple[UUID, UUID], SupplyTermsLike],
    ) -> frozenset[tuple[UUID, UUID]]:
        """Pass 1 (D-17): (supplier, store) pairs that need a PO regardless — short stores of products for which
        no store has surplus. `terms` is keyed by (store_id, product_id)."""
        marked: set[tuple[UUID, UUID]] = set()
        for product_id, states in states_by_product.items():
            if any(s.surplus > 0 for s in states):
                continue
            for s in states:
                if s.available < s.requirement:
                    marked.add((terms[(s.store_id, product_id)].supplier_id, s.store_id))
        return frozenset(marked)

    @staticmethod
    def find_expiry_receivers(
        product_id: UUID,
        qty: int,
        days_left: int,
        from_store: UUID,
        states: Sequence[StoreState],
        routes: RouteMap,
        unit_cost: Decimal,
    ) -> list[TransferProposal]:
        """Stores that can sell an at-risk batch before it expires (SD-08, D-28).

        A receiver needs a route with transit_days < days_left; its capacity is
        floor(daily_demand × (days_left − transit_days)). A transfer is proposed only if its incremental cost
        is below the value of the stock it saves (qty × unit_cost).
        1. Prefer a single receiver that can absorb the whole qty: cheapest transfer, then shorter transit,
           then store id.
        2. Only if none can, split: largest capacity first (ties by store id), skipping parts not worth moving.
        """
        candidates: list[tuple[int, UUID, TransferRouteLike]] = []
        for s in states:
            route = routes.get((from_store, s.store_id))
            if s.store_id == from_store or route is None or route.transit_days >= days_left:
                continue
            capacity = floor6(s.daily_demand * (days_left - route.transit_days))
            if capacity > 0:
                candidates.append((capacity, s.store_id, route))

        def worth_it(route: TransferRouteLike, give: int) -> bool:
            return CostModel.transfer_incremental_cost(route, give) < give * unit_cost

        def proposal(capacity: int, store_id: UUID, route: TransferRouteLike, give: int) -> TransferProposal:
            cost = CostModel.transfer_incremental_cost(route, give)
            return TransferProposal(
                from_store=from_store,
                to_store=store_id,
                product_id=product_id,
                qty=give,
                transfer_cost=money(cost),
                po_cost_avoided=Decimal("0.00"),
                transit_days=route.transit_days,
                evidence={
                    "days_left": days_left,
                    "at_risk": qty,
                    "sell_capacity": capacity,
                    "transit_days": route.transit_days,
                    "transfer_cost": str(money(cost)),
                    "value_at_risk": str(money(give * unit_cost)),
                },
            )

        singles = [c for c in candidates if c[0] >= qty and worth_it(c[2], qty)]
        if singles:
            best = min(
                singles,
                key=lambda c: (CostModel.transfer_incremental_cost(c[2], qty), c[2].transit_days, c[1]),
            )
            return [proposal(best[0], best[1], best[2], qty)]

        proposals: list[TransferProposal] = []
        remaining = qty
        for capacity, store_id, route in sorted(candidates, key=lambda c: (-c[0], c[1])):
            if remaining <= 0:
                break
            give = min(capacity, remaining)
            if not worth_it(route, give):
                continue
            proposals.append(proposal(capacity, store_id, route, give))
            remaining -= give
        return proposals


def _candidates(donors: Mapping[UUID, _Donor], to_store: UUID, routes: RouteMap) -> list[UUID]:
    """Donor ids by per-unit route cost, then id; donors without a route last (they are skipped)."""

    def key(donor_id: UUID) -> tuple[int, Decimal, UUID]:
        route = routes.get((donor_id, to_store))
        return (1, Decimal(0), donor_id) if route is None else (0, route.per_unit_cost, donor_id)

    return sorted(donors, key=key)


def _po_cost(
    qty: int, donor: StoreState, terms: SupplyTermsLike, short_store: UUID, cost_inputs: CostInputs
) -> Decimal:
    marked = (terms.supplier_id, short_store) in cost_inputs.planned_supplier_stores
    return CostModel.po_incremental_cost(
        qty=qty,
        unit_cost=terms.unit_cost,
        donor=donor,
        terms=terms,
        order_fixed_share=Decimal(0) if marked else cost_inputs.order_fixed_cost,
        delivery_charge_share=Decimal(0) if marked else terms.delivery_charge,
        holding_rate=cost_inputs.holding_cost_rate_per_day,
        expiry_risk_pct=cost_inputs.expiry_risk_pct,
        is_perishable=cost_inputs.is_perishable,
        days_to_sell_cap=cost_inputs.days_to_sell_cap,
    )


def _po_need(
    product_id: UUID,
    short: StoreState,
    qty: int,
    terms: SupplyTermsLike,
    reason: NeedReason,
    initial_need: int,
    transferred: int,
) -> PONeed:
    return PONeed(
        store_id=short.store_id,
        product_id=product_id,
        qty=qty,
        priority=TransferDecisionEngine._priority(short, terms.lead_time_days),
        reason=reason,
        supplier_id=terms.supplier_id,
        evidence={
            "requirement": short.requirement,
            "available": short.available,
            "need": initial_need,
            "transferred_qty": transferred,
            "po_qty": qty,
            "days_of_cover": round(short.days_of_cover, 2),
        },
    )
