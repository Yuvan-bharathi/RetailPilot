"""Property-based tests for TransferDecisionEngine (decision D-25)."""

import random
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from app.tools.transfer_engine import TransferDecisionEngine as TE
from app.tools.types import CostInputs, Route, StoreState, StoreSupplyTerms, TransferPlan
from tests.unit.tools.builders import PRODUCT, SUPPLIER

STORE_IDS = [UUID(int=i) for i in range(1, 6)]


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs]:
    n = draw(st.integers(min_value=2, max_value=5))
    stores = STORE_IDS[:n]
    states = [
        StoreState(
            store_id=s,
            requirement=draw(st.integers(0, 120)),
            available=draw(st.integers(0, 160)),
            daily_demand=draw(st.floats(0, 25, allow_nan=False, allow_infinity=False)),
        )
        for s in stores
    ]
    routes: dict[tuple[UUID, UUID], Route] = {}
    for a in stores:
        for b in stores:
            if a != b and draw(st.booleans()):
                routes[(a, b)] = Route(
                    fixed_cost=Decimal(draw(st.integers(0, 600))),
                    per_unit_cost=Decimal(draw(st.integers(0, 20))),
                    handling_cost_per_unit=Decimal(draw(st.integers(0, 5))),
                    transit_days=draw(st.integers(0, 10)),
                )
    terms = {
        s: StoreSupplyTerms(
            supplier_id=SUPPLIER,
            lead_time_days=draw(st.integers(1, 10)),
            delivery_charge=Decimal(draw(st.integers(0, 300))),
            unit_cost=Decimal(draw(st.integers(1, 500))),
        )
        for s in stores
    }
    planned = frozenset((SUPPLIER, s) for s in stores if draw(st.booleans()))
    cost_inputs = CostInputs(
        terms_by_store=terms,
        order_fixed_cost=Decimal(draw(st.integers(0, 500))),
        holding_cost_rate_per_day=Decimal("0.0005"),
        expiry_risk_pct=Decimal("0.10"),
        is_perishable=draw(st.booleans()),
        days_to_sell_cap=draw(st.integers(1, 120)),
        planned_supplier_stores=planned,
    )
    return states, routes, cost_inputs


def _flows(plan: TransferPlan) -> tuple[dict[UUID, int], dict[UUID, int], dict[UUID, int]]:
    sent: dict[UUID, int] = defaultdict(int)
    received: dict[UUID, int] = defaultdict(int)
    ordered: dict[UUID, int] = defaultdict(int)
    for t in plan.transfers:
        sent[t.from_store] += t.qty
        received[t.to_store] += t.qty
    for n in plan.po_needs:
        ordered[n.store_id] += n.qty
    return sent, received, ordered


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_no_donor_ends_below_its_own_requirement(
    scenario: tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs],
) -> None:
    states, routes, cost_inputs = scenario
    plan = TE.decide(PRODUCT, states, routes, cost_inputs)
    sent, _, _ = _flows(plan)

    for s in states:
        assert s.available - sent[s.store_id] >= s.requirement or sent[s.store_id] == 0


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_each_short_store_gets_exactly_its_need(
    scenario: tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs],
) -> None:
    states, routes, cost_inputs = scenario
    plan = TE.decide(PRODUCT, states, routes, cost_inputs)
    _, received, ordered = _flows(plan)

    for s in states:
        need = max(0, s.requirement - s.available)
        assert received[s.store_id] + ordered[s.store_id] == need


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_transfers_only_from_stores_with_surplus(
    scenario: tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs],
) -> None:
    states, routes, cost_inputs = scenario
    plan = TE.decide(PRODUCT, states, routes, cost_inputs)
    by_id = {s.store_id: s for s in states}

    for t in plan.transfers:
        assert by_id[t.from_store].surplus > 0
        assert t.qty > 0
        assert (t.from_store, t.to_store) in routes
        assert (
            routes[(t.from_store, t.to_store)].transit_days
            <= cost_inputs.terms_by_store[t.to_store].lead_time_days
        )


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_no_transfers_when_no_store_has_surplus(
    scenario: tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs],
) -> None:
    states, routes, cost_inputs = scenario
    # make every store hold at most its requirement
    capped = [
        StoreState(s.store_id, s.requirement, min(s.available, s.requirement), s.daily_demand) for s in states
    ]

    plan = TE.decide(PRODUCT, capped, routes, cost_inputs)

    assert plan.transfers == ()
    assert all(n.reason == "NO_SURPLUS_IN_ANY_STORE" for n in plan.po_needs)


@settings(max_examples=200, deadline=None)
@given(scenarios(), st.randoms(use_true_random=False))
def test_store_order_does_not_change_the_plan(
    scenario: tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs],
    rnd: random.Random,
) -> None:
    states, routes, cost_inputs = scenario
    shuffled = list(states)
    rnd.shuffle(shuffled)

    assert TE.decide(PRODUCT, shuffled, routes, cost_inputs) == TE.decide(
        PRODUCT, states, routes, cost_inputs
    )


@settings(max_examples=200, deadline=None)
@given(st.lists(scenarios(), min_size=1, max_size=4), st.randoms(use_true_random=False))
def test_product_order_does_not_change_pass_1_marking(
    products: list[tuple[list[StoreState], dict[tuple[UUID, UUID], Route], CostInputs]],
    rnd: random.Random,
) -> None:
    states_by_product = {UUID(int=0x1000 + i): p[0] for i, p in enumerate(products)}
    supply = {
        (s.store_id, product_id): products[i][2].terms_by_store[s.store_id]
        for i, (product_id, states) in enumerate(states_by_product.items())
        for s in states
    }
    items = list(states_by_product.items())
    rnd.shuffle(items)

    assert TE.mark_po_pairs(dict(items), supply) == TE.mark_po_pairs(states_by_product, supply)
