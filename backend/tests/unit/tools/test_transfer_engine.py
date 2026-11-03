"""TransferDecisionEngine — SD-07 step by step, D-04, D-10, D-17, D-24."""

from decimal import Decimal
from uuid import UUID

from app.tools.transfer_engine import TransferDecisionEngine as TE
from app.tools.types import PONeed, StoreState, TransferProposal
from tests.unit.tools.builders import (
    PRODUCT,
    STORE_A,
    STORE_B,
    STORE_C,
    SUPPLIER,
    all_routes,
    cost_inputs,
    route,
    terms,
)


def _state(store: UUID, requirement: int, available: int, daily_demand: float) -> StoreState:
    return StoreState(store_id=store, requirement=requirement, available=available, daily_demand=daily_demand)


def _worked_example_states() -> list[StoreState]:
    return [
        _state(STORE_A, requirement=30, available=54, daily_demand=3),  # surplus 24
        _state(STORE_B, requirement=50, available=50, daily_demand=5),  # sells fast, surplus 0
        _state(STORE_C, requirement=40, available=0, daily_demand=4),  # need 40
    ]


def test_worked_example_transfer_24_and_po_16() -> None:
    plan = TE.decide(PRODUCT, _worked_example_states(), all_routes(), cost_inputs())

    assert len(plan.transfers) == 1
    transfer = plan.transfers[0]
    assert (transfer.from_store, transfer.to_store, transfer.qty) == (STORE_A, STORE_C, 24)
    assert transfer.product_id == PRODUCT
    # transfer: 100 + 2×24 + 1×24 = 172 ; PO: 250 + 150 + 24×50×0.0005×(24/3 = 8 days) = 404.80
    assert transfer.transfer_cost == Decimal("172.00")
    assert transfer.po_cost_avoided == Decimal("404.80")
    assert transfer.transit_days == 1
    assert transfer.evidence["donor_surplus"] == 24
    assert transfer.evidence["donor_requirement"] == 30
    assert transfer.evidence["need"] == 40

    assert plan.po_needs == (
        PONeed(
            store_id=STORE_C,
            product_id=PRODUCT,
            qty=16,
            priority="HIGH",
            reason="PARTIAL_SURPLUS",
            supplier_id=SUPPLIER,
            evidence=plan.po_needs[0].evidence,
        ),
    )
    assert plan.po_needs[0].evidence["transferred_qty"] == 24


def test_sells_high_in_every_store_raises_po_only() -> None:
    states = [
        _state(STORE_A, requirement=60, available=20, daily_demand=8),
        _state(STORE_B, requirement=50, available=50, daily_demand=6),  # exactly at requirement → not a donor
        _state(STORE_C, requirement=40, available=10, daily_demand=5),
    ]

    plan = TE.decide(PRODUCT, states, all_routes(), cost_inputs())

    assert plan.transfers == ()
    assert [(n.store_id, n.qty, n.reason) for n in plan.po_needs] == [
        (STORE_C, 30, "NO_SURPLUS_IN_ANY_STORE"),  # cover 2.0 days — most urgent first
        (STORE_A, 40, "NO_SURPLUS_IN_ANY_STORE"),  # cover 2.5 days
    ]


def test_donor_is_never_taken_below_its_requirement() -> None:
    states = [
        _state(STORE_A, requirement=30, available=40, daily_demand=3),  # surplus 10
        _state(STORE_C, requirement=40, available=0, daily_demand=4),
    ]

    plan = TE.decide(PRODUCT, states, all_routes(), cost_inputs())

    assert [t.qty for t in plan.transfers] == [10]
    assert [(n.qty, n.reason) for n in plan.po_needs] == [(30, "PARTIAL_SURPLUS")]


def test_no_route_means_po_for_the_full_need() -> None:
    plan = TE.decide(PRODUCT, _worked_example_states(), routes={}, cost_inputs=cost_inputs())

    assert plan.transfers == ()
    assert [(n.qty, n.reason) for n in plan.po_needs] == [(40, "TRANSFER_NOT_VIABLE")]


def test_transfer_slower_than_supplier_lead_time_is_not_used() -> None:
    plan = TE.decide(PRODUCT, _worked_example_states(), all_routes(route(transit_days=6)), cost_inputs())

    assert plan.transfers == ()
    assert [(n.qty, n.reason) for n in plan.po_needs] == [(40, "TRANSFER_NOT_VIABLE")]


def test_transit_equal_to_lead_time_is_fast_enough() -> None:
    plan = TE.decide(PRODUCT, _worked_example_states(), all_routes(route(transit_days=5)), cost_inputs())

    assert [t.qty for t in plan.transfers] == [24]


def test_transfer_costlier_than_po_is_not_used() -> None:
    plan = TE.decide(PRODUCT, _worked_example_states(), all_routes(route(fixed="1000")), cost_inputs())

    assert plan.transfers == ()
    assert [n.reason for n in plan.po_needs] == ["TRANSFER_NOT_VIABLE"]


def test_marginal_order_cost_is_zero_when_the_pair_is_already_planned() -> None:
    # D-17: a PO to SUPPLIER for store C is happening anyway → only holding cost (4.80) is avoided,
    # which is less than the 172 transfer cost → buy instead.
    planned = frozenset({(SUPPLIER, STORE_C)})

    plan = TE.decide(PRODUCT, _worked_example_states(), all_routes(), cost_inputs(planned=planned))

    assert plan.transfers == ()
    assert [(n.qty, n.reason) for n in plan.po_needs] == [(40, "TRANSFER_NOT_VIABLE")]


def test_cheapest_route_donor_is_used_first() -> None:
    states = [
        _state(STORE_A, requirement=10, available=20, daily_demand=1),  # surplus 10
        _state(STORE_B, requirement=10, available=20, daily_demand=1),  # surplus 10
        _state(STORE_C, requirement=15, available=0, daily_demand=1),
    ]
    routes = all_routes()
    routes[(STORE_A, STORE_C)] = route(per_unit="3")
    routes[(STORE_B, STORE_C)] = route(per_unit="1")

    plan = TE.decide(PRODUCT, states, routes, cost_inputs())

    assert [(t.from_store, t.qty) for t in plan.transfers] == [(STORE_B, 10), (STORE_A, 5)]
    assert plan.po_needs == ()


def test_most_urgent_short_store_is_served_first() -> None:
    states = [
        _state(STORE_A, requirement=10, available=20, daily_demand=1),  # surplus 10
        _state(STORE_B, requirement=30, available=20, daily_demand=2),  # cover 10 days
        _state(STORE_C, requirement=30, available=0, daily_demand=2),  # cover 0 days → first
    ]

    plan = TE.decide(PRODUCT, states, all_routes(), cost_inputs())

    assert [(t.to_store, t.qty) for t in plan.transfers] == [(STORE_C, 10)]
    # donor exhausted → store B's PO says no surplus is left anywhere
    assert [(n.store_id, n.qty, n.reason) for n in plan.po_needs] == [
        (STORE_C, 20, "PARTIAL_SURPLUS"),
        (STORE_B, 10, "NO_SURPLUS_IN_ANY_STORE"),
    ]


def test_no_short_store_gives_an_empty_plan() -> None:
    states = [_state(STORE_A, 10, 20, 1), _state(STORE_B, 10, 10, 1)]

    plan = TE.decide(PRODUCT, states, all_routes(), cost_inputs())

    assert plan.transfers == () and plan.po_needs == ()


def test_priority() -> None:
    urgent = _state(STORE_C, requirement=40, available=8, daily_demand=4)  # 2 days of cover
    calm = _state(STORE_C, requirement=40, available=24, daily_demand=4)  # 6 days of cover

    assert TE._priority(urgent, lead_time_days=5) == "HIGH"
    assert TE._priority(calm, lead_time_days=5) == "NORMAL"


def test_mark_po_pairs_marks_short_stores_of_products_without_any_surplus() -> None:
    other_product = UUID(int=0x200)
    other_supplier = UUID(int=0x6)
    states_by_product = {
        PRODUCT: [_state(STORE_A, 60, 20, 8), _state(STORE_B, 50, 50, 6), _state(STORE_C, 40, 10, 5)],
        other_product: [_state(STORE_A, 10, 30, 1), _state(STORE_C, 40, 0, 4)],  # A has surplus
    }
    supply = {
        (STORE_A, PRODUCT): terms(),
        (STORE_B, PRODUCT): terms(),
        (STORE_C, PRODUCT): terms(supplier_id=other_supplier),
        (STORE_A, other_product): terms(),
        (STORE_C, other_product): terms(),
    }

    marked = TE.mark_po_pairs(states_by_product, supply)

    assert marked == frozenset({(SUPPLIER, STORE_A), (other_supplier, STORE_C)})


UNIT_COST = Decimal("50")


def _expiry_states() -> list[StoreState]:
    return [
        _state(STORE_A, 10, 40, 1),  # the store holding the batch
        _state(STORE_B, 10, 10, 2),  # capacity floor(2 × (10 − 1)) = 18
        _state(STORE_C, 10, 10, 5),  # capacity floor(5 × (10 − 2)) = 40
    ]


EXPIRY_ROUTES = {(STORE_A, STORE_B): route(transit_days=1), (STORE_A, STORE_C): route(transit_days=2)}


def test_find_expiry_receivers_single_receiver_that_absorbs_everything() -> None:
    receivers = TE.find_expiry_receivers(PRODUCT, 30, 10, STORE_A, _expiry_states(), EXPIRY_ROUTES, UNIT_COST)

    assert [(r.to_store, r.qty) for r in receivers] == [(STORE_C, 30)]  # only C can take all 30
    assert isinstance(receivers[0], TransferProposal)
    assert receivers[0].evidence["days_left"] == 10
    assert receivers[0].evidence["sell_capacity"] == 40
    assert receivers[0].evidence["value_at_risk"] == "1500.00"  # 30 × 50


def test_find_expiry_receivers_cheapest_single_receiver_wins_over_largest_capacity() -> None:
    # D-28: both B (capacity 18) and C (capacity 40) can absorb 15 units → the cheaper transfer (B) is chosen.
    routes = {
        (STORE_A, STORE_B): route(fixed="50", transit_days=1),
        (STORE_A, STORE_C): route(fixed="100", transit_days=2),
    }

    receivers = TE.find_expiry_receivers(PRODUCT, 15, 10, STORE_A, _expiry_states(), routes, UNIT_COST)

    assert [(r.to_store, r.qty) for r in receivers] == [(STORE_B, 15)]


def test_find_expiry_receivers_splits_only_when_no_single_store_can_absorb() -> None:
    store_d = UUID(int=0xD)
    states = [*_expiry_states(), _state(store_d, 10, 10, 1)]  # D: capacity floor(1 × 9) = 9, never needed
    routes = {**EXPIRY_ROUTES, (STORE_A, store_d): route(transit_days=1)}

    receivers = TE.find_expiry_receivers(PRODUCT, 50, 10, STORE_A, states, routes, UNIT_COST)

    assert [(r.to_store, r.qty) for r in receivers] == [(STORE_C, 40), (STORE_B, 10)]


def test_find_expiry_receivers_only_when_transfer_costs_less_than_the_stock_saved() -> None:
    # transfer of 30 to C costs 100 + 2×30 + 1×30 = 190
    too_cheap_stock = TE.find_expiry_receivers(
        PRODUCT, 30, 10, STORE_A, _expiry_states(), EXPIRY_ROUTES, Decimal("5")
    )
    worth_it = TE.find_expiry_receivers(
        PRODUCT, 30, 10, STORE_A, _expiry_states(), EXPIRY_ROUTES, Decimal("10")
    )

    assert too_cheap_stock == []  # 190 ≥ 30 × 5 = 150
    assert [(r.to_store, r.qty) for r in worth_it] == [(STORE_C, 30)]  # 190 < 300


def test_find_expiry_receivers_split_skips_parts_not_worth_moving() -> None:
    # split of 50: C 40 costs 220 < 400 ✓ ; B 10 costs 100 + 20 + 10 = 130 ≥ 10 × 10 = 100 ✗
    receivers = TE.find_expiry_receivers(
        PRODUCT, 50, 10, STORE_A, _expiry_states(), EXPIRY_ROUTES, Decimal("10")
    )

    assert [(r.to_store, r.qty) for r in receivers] == [(STORE_C, 40)]


def test_find_expiry_receivers_excludes_slow_unrouted_and_idle_stores() -> None:
    states = [
        _state(STORE_A, 10, 40, 1),
        _state(STORE_B, 10, 10, 5),  # route too slow (transit 10 ≥ days_left 10)
        _state(STORE_C, 10, 10, 0),  # no demand → cannot sell it
        _state(UUID(int=0xD), 10, 10, 9),  # no route from A
    ]
    routes = {(STORE_A, STORE_B): route(transit_days=10), (STORE_A, STORE_C): route(transit_days=1)}

    assert TE.find_expiry_receivers(PRODUCT, 30, 10, STORE_A, states, routes, UNIT_COST) == []
