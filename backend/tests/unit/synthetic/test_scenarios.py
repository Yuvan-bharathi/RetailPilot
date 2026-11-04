"""The five demo scenarios (docs/04-demo-scenarios.md) are planted so the real tools reproduce them."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.tools.basket import BasketTools
from app.tools.freshness import FreshnessTools
from app.tools.requirement import RequirementCalculator as RC
from app.tools.transfer_engine import TransferDecisionEngine as TE
from app.tools.types import BasketQualityRules, BatchInfo
from data.synthetic.reader import Dataset
from scripts.planning import Planner


def _store(ds: Dataset, code: str) -> UUID:
    return UUID(ds.manifest["stores"][code])


def _scenario(ds: Dataset, number: int) -> dict[str, Any]:
    scenario: dict[str, Any] = ds.manifest["scenarios"][str(number)]
    return scenario


@pytest.mark.parametrize("number", [1, 2, 3])
def test_planted_demand_requirement_and_stock_match_the_manifest(
    dataset: Dataset, planner: Planner, number: int
) -> None:
    scenario = _scenario(dataset, number)
    product = UUID(scenario["product_id"])

    for code, planted in scenario["planted"].items():
        store = _store(dataset, code)
        assert planner.demand(store, product) == planted["daily_demand"], code
        assert planner.requirement(store, product) == planted["requirement"], code
        assert planner.available(store, product) == planted["on_hand"], code


def test_scenario_1_fast_mover_everywhere_raises_po_only(dataset: Dataset, planner: Planner) -> None:
    scenario = _scenario(dataset, 1)

    plan = planner.decide(UUID(scenario["product_id"]))

    assert plan.transfers == ()
    expected = {_store(dataset, code): qty for code, qty in scenario["expected"]["po_needs"].items()}
    assert {n.store_id: n.qty for n in plan.po_needs} == expected
    assert {n.reason for n in plan.po_needs} == {"NO_SURPLUS_IN_ANY_STORE"}
    assert {n.supplier_id for n in plan.po_needs} == {UUID(scenario["supplier_id"])}  # one consolidated PO


def test_scenario_2_surplus_transfer_without_po(dataset: Dataset, planner: Planner) -> None:
    scenario = _scenario(dataset, 2)

    plan = planner.decide(UUID(scenario["product_id"]))

    assert [(t.from_store, t.to_store, t.qty) for t in plan.transfers] == [
        (_store(dataset, "A"), _store(dataset, "C"), scenario["expected"]["transfer_qty"])
    ]
    assert plan.po_needs == ()
    assert plan.transfers[0].transfer_cost < plan.transfers[0].po_cost_avoided


def test_scenario_3_worked_example_transfer_24_and_po_16(dataset: Dataset, planner: Planner) -> None:
    scenario = _scenario(dataset, 3)
    store_a, store_b, store_c = (_store(dataset, c) for c in "ABC")

    plan = planner.decide(UUID(scenario["product_id"]))

    assert [(t.from_store, t.to_store, t.qty) for t in plan.transfers] == [(store_a, store_c, 24)]
    assert [(n.store_id, n.qty, n.reason) for n in plan.po_needs] == [(store_c, 16, "PARTIAL_SURPLUS")]
    # Store B sits exactly at its own requirement: no surplus, no need, nothing proposed for it.
    state_b = planner.state(store_b, UUID(scenario["product_id"]))
    assert state_b.surplus == 0
    assert all(store_b not in (t.from_store, t.to_store) for t in plan.transfers)
    assert all(n.store_id != store_b for n in plan.po_needs)


def test_scenario_4_bread_reorder_pulls_butter_in(dataset: Dataset, planner: Planner) -> None:
    scenario = _scenario(dataset, 4)
    store = _store(dataset, scenario["store"])
    bread, butter = UUID(scenario["bread_id"]), UUID(scenario["butter_id"])
    expected = scenario["expected"]

    # bread is short in the store and nobody has surplus → SHORTFALL PO need to the bread supplier
    plan = planner.decide(bread)
    assert plan.transfers == ()
    assert [(n.store_id, n.qty, n.reason) for n in plan.po_needs] == [
        (store, expected["bread_po_qty"], "NO_SURPLUS_IN_ANY_STORE")
    ]
    supplier = plan.po_needs[0].supplier_id

    # butter: not short today, but falls below its requirement before the next review (D-02)
    butter_state = planner.state(store, butter)
    assert butter_state.available >= butter_state.requirement
    qty = RC.co_replenish_qty(
        butter_state.available,
        butter_state.daily_demand,
        butter_state.review_period_days,
        butter_state.requirement,
    )
    assert qty == expected["butter_co_replenish_qty"]
    # D-13: butter's preferred supplier already delivers bread to the same store this cycle
    assert planner.preferred_supplier(store, butter) == supplier

    # the bread → butter rule is mined from the store's own bills with lift ≥ 1.5
    rules = _store_rules(dataset, planner, store)
    bread_rules = rules.loc[(rules["antecedent_id"] == bread) & (rules["lift"] >= 1.5)]
    top3 = list(bread_rules.sort_values("lift", ascending=False)["consequent_id"].head(3))
    assert butter in top3


def _store_rules(dataset: Dataset, planner: Planner, store: UUID) -> Any:
    lines = dataset.sales_lines
    start = planner.end_date - timedelta(days=89)
    recent = lines.loc[(lines["store_id"] == store) & (lines["txn_date"] >= start)]
    basket_rules = planner.rules["basket"]
    cleaned = BasketTools.clean_bills(
        recent,
        BasketQualityRules(
            max_qty_per_line=int(basket_rules["max_qty_per_line"]),
            exclude_promo_days=bool(basket_rules["exclude_promo_days"]),
        ),
    )
    assert cleaned["bill_id"].nunique() >= int(basket_rules["min_bills"])
    return BasketTools.mine_rules(
        BasketTools.to_basket_matrix(cleaned),
        min_support=float(basket_rules["min_support"]),
        min_confidence=float(basket_rules["min_confidence"]),
        min_lift=float(basket_rules["min_lift"]),
    )


def test_scenario_5_expiring_batch_goes_to_the_store_that_can_sell_it(
    dataset: Dataset, planner: Planner
) -> None:
    scenario = _scenario(dataset, 5)
    product = UUID(scenario["product_id"])
    store_a, store_c = _store(dataset, scenario["from"]), _store(dataset, scenario["to"])
    expected = scenario["expected"]

    batches = dataset.batches.loc[
        (dataset.batches["store_id"] == store_a) & (dataset.batches["product_id"] == product)
    ]
    infos = [BatchInfo(r.batch_id, int(r.qty), r.expiry_date) for r in batches.itertuples()]
    risks = FreshnessTools.at_risk_by_batch(infos, planner.demand(store_a, product), planner.run_date)
    risky = [r for r in risks if r.at_risk > 0]
    assert [(r.batch_id, r.days_left, r.at_risk) for r in risky] == [
        (UUID(scenario["batch_id"]), expected["days_left"], expected["at_risk"])
    ]

    receivers = TE.find_expiry_receivers(
        product,
        risky[0].at_risk,
        risky[0].days_left,
        store_a,
        planner.states(product),
        planner.routes(),
        planner.unit_cost(store_a, product),
    )
    assert [(r.to_store, r.qty) for r in receivers] == [
        (store_c, expected["at_risk"])
    ]  # one receiver, all of it

    # no store is short of it, so stock balancing alone would not move it
    assert planner.decide(product).transfers == ()


def test_run_and_end_dates(dataset: Dataset) -> None:
    end = date.fromisoformat(dataset.manifest["end_date"])
    assert date.fromisoformat(dataset.manifest["run_date"]) == end + timedelta(days=1)
    assert sorted(dataset.manifest["scenarios"]) == ["1", "2", "3", "4", "5"]
