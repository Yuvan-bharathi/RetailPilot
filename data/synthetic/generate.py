"""Synthetic data generator for RetailPilot AI (Phase 4a).

From the repo root:
    uv run --project backend python -m data.synthetic.generate --scenarios all --profile full --seed 42

Writes the CSV files described in data/synthetic/README.md plus business_rules.json and manifest.json.
The same seed and profile always produce byte-identical files.
"""

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from data.synthetic.bills import Sold, build_day
from data.synthetic.catalog import (
    CATEGORY_BY_NAME,
    REGION,
    STORES,
    Offer,
    Product,
    Store,
    Supplier,
    background_suppliers,
    make_background_products,
    make_calendar,
    make_routes,
    uid,
)
from data.synthetic.config import ALL_SCENARIOS, PROFILES, GeneratorConfig
from data.synthetic.demand import background_demand, day_factor, expected_rate
from data.synthetic.inventory import Policy, SimResult, last_review_day, scenario_plan, simulate
from data.synthetic.scenarios import Scenario, ScenarioProduct, build_scenarios
from data.synthetic.writer import write_csv, write_json

CSV_FILES: tuple[str, ...] = (
    "stores.csv",
    "products.csv",
    "suppliers.csv",
    "supplier_products.csv",
    "supplier_store_terms.csv",
    "store_products.csv",
    "transfer_routes.csv",
    "calendar_events.csv",
    "sales_bills.csv",
    "sales_lines.csv",
    "stock_snapshots.csv",
    "receipts.csv",
    "write_offs.csv",
    "batches.csv",
    "open_orders.csv",
)

BUSINESS_RULES: dict[str, Any] = {
    "po_l2_threshold": "50000",
    "weekly_budget": "500000",
    "order_fixed_cost": "250",
    "holding_cost_rate_per_day": "0.0005",
    "expiry_risk_pct": "0.10",
    "perishable_max_shelf_life_days": 30,
    "days_to_sell_default_cap": 90,
    "incoming_overdue_grace_days": 3,
    "l1_deadline_hours": 24,
    "deadline_action": "ESCALATE",
    "stale_days": 3,
    "kpi_lookback_days": 28,
    "expiry_window_days": 14,
    "max_steps": 50,
    "basket": {
        "min_bills": 500,
        "min_support": 0.005,
        "min_confidence": 0.2,
        "min_lift": 1.0,
        "max_qty_per_line": 24,
        "max_qty_per_line_by_category": {},
        "exclude_promo_days": True,
    },
    "co_replenish": {"min_lift": 1.5, "limit": 3},
}

BULK_QTY = 30
BULK_EVERY_DAYS = 15
COMPLEMENT_PROBABILITY = 0.9
MISMATCH_UNITS = 3
STALE_WINDOW_DAYS = 5


@dataclass(slots=True)
class _Item:
    """A store-product being simulated."""

    store: Store
    product: Product
    supplier: Supplier
    min_display_qty: int
    safety_stock_days: int
    demand: np.ndarray
    bulk: np.ndarray
    result: SimResult | None = None


def _offers(rng: np.random.Generator, products: Sequence[Product]) -> list[Offer]:
    suppliers = background_suppliers()
    offers: list[Offer] = []
    for p in products:
        for supplier in suppliers[p.category]:
            factor = Decimal(str(round(float(rng.uniform(0.97, 1.06)), 3)))
            moq = 0 if rng.random() < 0.6 else p.order_pack_size
            offers.append(
                Offer(
                    supplier,
                    p,
                    (p.cost_price * factor).quantize(Decimal("0.01")),
                    int(rng.integers(2, 8)),
                    moq,
                )
            )
    return offers


def _preferred(offers: Sequence[Offer]) -> dict[UUID, Supplier]:
    best: dict[UUID, Offer] = {}
    for o in offers:
        current = best.get(o.product.product_id)
        if current is None or (o.price, o.supplier.key) < (current.price, current.supplier.key):
            best[o.product.product_id] = o
    return {pid: o.supplier for pid, o in best.items()}


def _shelf_capacity(rate: float, min_display: int) -> int:
    return max(6, 2 * min_display, math.ceil(rate * 2))


def generate(config: GeneratorConfig, out_dir: Path) -> dict[str, Any]:
    """Generate the dataset into `out_dir` and return the manifest."""
    profile = config.resolved_profile
    rng = np.random.default_rng(config.seed)
    days = config.days
    n_days = len(days)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenarios = build_scenarios(config.scenarios)
    scenario_items: list[tuple[Scenario, str, ScenarioProduct]] = [
        (s, key, sp) for s in scenarios for key, sp in s.products.items()
    ]
    background = make_background_products(rng, profile.n_products - len(scenario_items))
    offers = _offers(rng, background)
    preferred = _preferred(offers)
    routes = make_routes(rng)
    events = make_calendar(config.start_date, config.end_date)
    festivals = [e.event_date for e in events if e.event_type == "FESTIVAL"]
    promo_days = {e.event_date for e in events if e.event_type == "PROMO"}
    for s, _, sp in scenario_items:
        offers.append(Offer(s.supplier, sp.product, sp.product.cost_price, 4, 0))
        preferred[sp.product.product_id] = s.supplier

    # --- simulate stock -----------------------------------------------------------------------------------------------
    items: list[_Item] = []
    edge: dict[str, dict[str, Any]] = {}
    for store in STORES:
        demand = background_demand(rng, background, store, days, festivals)
        bulk = np.zeros_like(demand)
        staples = [j for j, p in enumerate(background) if p.category == "staples"]
        if staples:
            top = max(staples, key=lambda j: (expected_rate(background[j], store), background[j].sku))
            bulk[BULK_EVERY_DAYS // 2 :: BULK_EVERY_DAYS, top] = BULK_QTY
        store_items: list[_Item] = []
        for j, p in enumerate(background):
            store_items.append(
                _Item(
                    store,
                    p,
                    preferred[p.product_id],
                    int(rng.integers(3, 11)),
                    int(rng.integers(1, 4)),
                    demand[:, j].copy(),
                    bulk[:, j].copy(),
                )
            )
        candidates = sorted(
            (it for it in store_items if it.product.shelf_life_days is None),
            key=lambda it: (-expected_rate(it.product, store), it.product.sku),
        )
        for it in store_items:
            _simulate_background(rng, it, days)
        if store.code == "B":
            edge["stock_mismatch"] = _plant_mismatch(rng, candidates, days)
        if store.code == "C":
            edge["stale_sku"] = _plant_stale(rng, candidates, days, config.run_date)
        items.extend(store_items)

    for s, _key, sp in scenario_items:
        for store in STORES:
            plant = sp.plants[store.code]
            # scenario 5: the donor store gets near-dated supply so its final batch expires
            # `final_batch_expiry_days` after the run date (every delivery has the same age → FEFO order holds)
            age: int | None = None
            if sp.final_batch_expiry_days is not None and s.extra.get("from") == store.code:
                final_expiry = config.run_date + timedelta(days=sp.final_batch_expiry_days)
                age = (final_expiry - days[last_review_day(n_days, store.review_period_days)]).days
            opening, plan = scenario_plan(
                plant.daily_demand, n_days, store.review_period_days, plant.on_hand, days[0], age
            )
            shelf_life = sp.product.shelf_life_days
            item = _Item(
                store,
                sp.product,
                s.supplier,
                plant.min_display_qty,
                plant.safety_stock_days,
                np.full(n_days, plant.daily_demand, dtype=np.int64),
                np.zeros(n_days, dtype=np.int64),
            )
            item.result = simulate(
                days=days,
                demand=item.demand,
                bulk=item.bulk,
                shelf_life=shelf_life,
                shelf_capacity=_shelf_capacity(plant.daily_demand, plant.min_display_qty),
                batch_prefix=f"{store.code}-{sp.product.sku}",
                opening_qty=opening,
                opening_expiry=(
                    None
                    if shelf_life is None
                    else days[0] + timedelta(days=age if age is not None else shelf_life)
                ),
                plan=plan,
            )
            items.append(item)

    # --- bills ----------------------------------------------------------------------------------------------------------
    pairs = _complement_pairs(rng, background, scenario_items)
    catalog = [(p.product_id, p.selling_price) for p in background]
    bill_rows: list[dict[str, object]] = []
    line_rows: list[dict[str, object]] = []
    for store in STORES:
        store_items = [it for it in items if it.store == store]
        for t, day in enumerate(days):
            assert all(it.result is not None for it in store_items)
            sold = [
                Sold(it.product.product_id, it.result.sales[t], it.product.selling_price)  # type: ignore[union-attr]
                for it in store_items
                if it.result.sales[t] > 0  # type: ignore[union-attr]
            ]
            bulk_sold = [
                Sold(it.product.product_id, it.result.bulk_sales[t], it.product.selling_price)  # type: ignore[union-attr]
                for it in store_items
                if it.result.bulk_sales[t] > 0  # type: ignore[union-attr]
            ]
            n_bills = max(10, round(profile.bills_per_store_day * day_factor(day)))
            bills, lines = build_day(
                rng,
                store_code=store.code,
                store_id=store.store_id,
                day=day,
                n_bills=n_bills,
                sold=sold,
                bulk=bulk_sold,
                pairs=pairs,
                promo=day in promo_days,
                catalog=catalog,
            )
            bill_rows.extend(bills)
            line_rows.extend(lines)

    manifest = _manifest(config, scenarios, edge, items)
    _write_all(
        out_dir,
        config,
        background,
        scenario_items,
        offers,
        preferred,
        items,
        routes,
        events,
        bill_rows,
        line_rows,
    )
    write_json(out_dir, "business_rules.json", BUSINESS_RULES)
    write_json(out_dir, "manifest.json", manifest)
    return manifest


def _policy(rng: np.random.Generator, it: _Item) -> Policy:
    return Policy(
        lead_time_days=it.store.lead_time_days,
        review_period_days=it.store.review_period_days,
        review_offset=int(rng.integers(it.store.review_period_days)),
        safety_stock_days=it.safety_stock_days,
        min_display_qty=it.min_display_qty,
        order_pack_size=it.product.order_pack_size,
        initial_rate=expected_rate(it.product, it.store),
    )


def _simulate_background(
    rng: np.random.Generator, it: _Item, days: list[date], shrinkage: tuple[int, int] | None = None
) -> None:
    rate = expected_rate(it.product, it.store)
    policy = _policy(rng, it)
    opening = (
        math.ceil(rate * (policy.lead_time_days + policy.review_period_days + policy.safety_stock_days))
        + policy.min_display_qty
        + int(rng.integers(0, math.ceil(rate * policy.review_period_days) + 1))
    )
    shelf_life = it.product.shelf_life_days
    opening_expiry = (
        None if shelf_life is None else days[0] + timedelta(days=int(rng.integers(1, shelf_life + 1)))
    )
    it.result = simulate(
        days=days,
        demand=it.demand,
        bulk=it.bulk,
        shelf_life=shelf_life,
        shelf_capacity=_shelf_capacity(rate, it.min_display_qty),
        batch_prefix=f"{it.store.code}-{it.product.sku}",
        opening_qty=opening,
        opening_expiry=opening_expiry,
        policy=policy,
        shrinkage=shrinkage,
    )


def _plant_mismatch(rng: np.random.Generator, candidates: list[_Item], days: list[date]) -> dict[str, Any]:
    """Unrecorded shrinkage of 3 units on one day: the POS snapshot is 3 below the ledger replay."""
    day_index = len(days) - 11
    for it in candidates:
        state = rng.bit_generator.state
        _simulate_background(rng, it, days, shrinkage=(day_index, MISMATCH_UNITS))
        assert it.result is not None
        if it.result.shrinkage_day == day_index:
            return {
                "store_id": str(it.store.store_id),
                "product_id": str(it.product.product_id),
                "date": days[day_index].isoformat(),
                "delta": -MISMATCH_UNITS,
            }
        rng.bit_generator.state = state
        _simulate_background(rng, it, days)  # restore the unplanted history for this product
    raise RuntimeError("no product had enough stock to plant the stock mismatch")


def _plant_stale(
    rng: np.random.Generator, candidates: list[_Item], days: list[date], run_date: date
) -> dict[str, Any]:
    """No sales for the last days while stock is held → stale SKU (low-confidence forecast, SD-02)."""
    for it in candidates:
        original = it.demand.copy()
        it.demand[-STALE_WINDOW_DAYS:] = 0
        it.bulk[-STALE_WINDOW_DAYS:] = 0
        state = rng.bit_generator.state
        _simulate_background(rng, it, days)
        assert it.result is not None
        sale_days = [days[t] for t, units in enumerate(it.result.sales) if units > 0]
        if it.result.closing[-1] > 0 and sale_days:
            return {
                "store_id": str(it.store.store_id),
                "product_id": str(it.product.product_id),
                "last_sale_date": max(sale_days).isoformat(),
                "days_without_sales": (run_date - max(sale_days)).days,
            }
        it.demand = original
        rng.bit_generator.state = state
        _simulate_background(rng, it, days)
    raise RuntimeError("no product had stock to plant the stale SKU")


def _complement_pairs(
    rng: np.random.Generator,
    background: Sequence[Product],
    scenario_items: Sequence[tuple[Scenario, str, ScenarioProduct]],
) -> dict[UUID, tuple[UUID, float]]:
    """complement product id → (anchor product id, probability its lines join an anchor bill)."""
    pairs: dict[UUID, tuple[UUID, float]] = {}
    by_key = {(s.number, key): sp.product for s, key, sp in scenario_items}
    if (4, "bread") in by_key:
        pairs[by_key[(4, "butter")].product_id] = (by_key[(4, "bread")].product_id, COMPLEMENT_PROBABILITY)
    biscuits = [p for p in background if p.category == "biscuits"]
    beverages = [p for p in background if p.category == "beverages"]
    for anchor, complement in list(zip(beverages, biscuits, strict=False))[:3]:
        pairs[complement.product_id] = (anchor.product_id, 0.5)
    del rng  # pairs are chosen deterministically from the catalogue order
    return pairs


def _manifest(
    config: GeneratorConfig,
    scenarios: Sequence[Scenario],
    edge: dict[str, dict[str, Any]],
    items: Sequence[_Item],
) -> dict[str, Any]:
    stores = {s.code: str(s.store_id) for s in STORES}
    entries: dict[str, Any] = {}
    for s in scenarios:
        entry: dict[str, Any] = {
            "title": s.title,
            "supplier_id": str(s.supplier.supplier_id),
            "products": {key: str(sp.product.product_id) for key, sp in s.products.items()},
            "planted": {
                key: {
                    code: {
                        "daily_demand": plant.daily_demand,
                        "safety_stock_days": plant.safety_stock_days,
                        "min_display_qty": plant.min_display_qty,
                        "requirement": plant.requirement(code),
                        "on_hand": plant.on_hand,
                    }
                    for code, plant in sp.plants.items()
                }
                for key, sp in s.products.items()
            },
            "expected": s.expected,
            **s.extra,
        }
        if "main" in s.products:
            entry["product_id"] = entry["products"]["main"]
            entry["planted"] = entry["planted"]["main"]
        if s.number == 4:
            entry["bread_id"] = entry["products"]["bread"]
            entry["butter_id"] = entry["products"]["butter"]
        if s.number == 5:
            sp = s.products["main"]
            item = next(it for it in items if it.product is sp.product and it.store.code == s.extra["from"])
            assert item.result is not None
            near_dated = [b for b in item.result.batches if b.expiry is not None]
            entry["batch_id"] = str(uid("batch", item.store.code, sp.product.sku, near_dated[-1].batch_no))
        entries[str(s.number)] = entry
    return {
        "seed": config.seed,
        "profile": config.resolved_profile.name,
        "end_date": config.end_date.isoformat(),
        "run_date": config.run_date.isoformat(),
        "stores": stores,
        "scenario_product_ids": [str(sp.product.product_id) for s in scenarios for sp in s.products.values()],
        "scenarios": entries,
        "edge_cases": edge,
        "notes": [
            "All data is synthetic. Festival dates are approximate.",
            "Scenario 3: Store C must hold 0, so its last day closes at 0 (a stockout day excluded from the "
            "baseline, D-30); its other days have the same constant demand.",
            "Return and voided lines do not move stock; replay uses lines that are neither.",
        ],
    }


def _write_all(
    out: Path,
    config: GeneratorConfig,
    background: Sequence[Product],
    scenario_items: Sequence[tuple[Scenario, str, ScenarioProduct]],
    offers: Sequence[Offer],
    preferred: dict[UUID, Supplier],
    items: Sequence[_Item],
    routes: Sequence[Any],
    events: Sequence[Any],
    bill_rows: list[dict[str, object]],
    line_rows: list[dict[str, object]],
) -> None:
    days = config.days
    products = [*background, *(sp.product for _, _, sp in scenario_items)]
    suppliers = {o.supplier.key: o.supplier for o in offers}
    write_csv(
        out,
        "stores.csv",
        (
            {
                "store_id": s.store_id,
                "code": s.code,
                "name": s.name,
                "region": REGION,
                "store_type": s.store_type,
                "display_capacity": s.display_capacity,
            }
            for s in STORES
        ),
    )
    write_csv(
        out,
        "products.csv",
        (
            {
                "product_id": p.product_id,
                "sku": p.sku,
                "name": p.name,
                "category": CATEGORY_BY_NAME[p.category].name,
                "brand": p.brand,
                "cost_price": p.cost_price,
                "selling_price": p.selling_price,
                "pack_size": 1,
                "shelf_life_days": p.shelf_life_days,
            }
            for p in products
        ),
    )
    write_csv(
        out,
        "suppliers.csv",
        (
            {"supplier_id": s.supplier_id, "name": s.name, "default_lead_time_days": s.default_lead_time_days}
            for _, s in sorted(suppliers.items())
        ),
    )
    write_csv(
        out,
        "supplier_products.csv",
        (
            {
                "supplier_id": o.supplier.supplier_id,
                "product_id": o.product.product_id,
                "price": o.price,
                "lead_time_days": o.lead_time_days,
                "moq": o.moq,
                "order_pack_size": o.product.order_pack_size,
            }
            for o in offers
        ),
    )
    write_csv(
        out,
        "supplier_store_terms.csv",
        (
            {
                "supplier_id": s.supplier_id,
                "store_id": store.store_id,
                "lead_time_days": store.lead_time_days,
                "delivery_charge": store.delivery_charge,
            }
            for _, s in sorted(suppliers.items())
            for store in STORES
        ),
    )
    write_csv(
        out,
        "store_products.csv",
        (
            {
                "store_id": it.store.store_id,
                "product_id": it.product.product_id,
                "preferred_supplier_id": preferred[it.product.product_id].supplier_id,
                "min_display_qty": it.min_display_qty,
                "safety_stock_days": it.safety_stock_days,
                "review_period_days": it.store.review_period_days,
                "is_listed": True,
            }
            for it in items
        ),
    )
    write_csv(
        out,
        "transfer_routes.csv",
        (
            {
                "from_store_id": r.from_store.store_id,
                "to_store_id": r.to_store.store_id,
                "fixed_cost": r.fixed_cost,
                "per_unit_cost": r.per_unit_cost,
                "handling_cost_per_unit": r.handling_cost_per_unit,
                "transit_days": r.transit_days,
            }
            for r in routes
        ),
    )
    write_csv(
        out,
        "calendar_events.csv",
        (
            {
                "event_id": uid("event", e.event_type, e.event_date.isoformat()),
                "event_date": e.event_date,
                "event_type": e.event_type,
                "region": REGION,
                "description": e.description,
            }
            for e in events
        ),
    )
    write_csv(out, "sales_bills.csv", bill_rows)
    write_csv(out, "sales_lines.csv", line_rows)

    snapshots: list[dict[str, object]] = []
    receipts: list[dict[str, object]] = []
    write_offs: list[dict[str, object]] = []
    batches: list[dict[str, object]] = []
    open_orders: list[dict[str, object]] = []
    for it in items:
        r = it.result
        assert r is not None
        key = {"store_id": it.store.store_id, "product_id": it.product.product_id}
        for t, day in enumerate(days):
            snapshots.append(
                {
                    **key,
                    "snapshot_date": day,
                    "shelf_qty": r.shelf[t],
                    "backroom_qty": r.closing[t] - r.shelf[t],
                    "closing_on_hand": r.closing[t],
                }
            )
        for t, qty, batch_no, expiry in r.receipts:
            receipts.append(
                {
                    "receipt_id": uid("receipt", it.store.code, it.product.sku, batch_no),
                    **key,
                    "supplier_id": it.supplier.supplier_id,
                    "receipt_date": days[t],
                    "qty": qty,
                    "batch_no": batch_no,
                    "expiry_date": expiry,
                }
            )
        for t, batch_no, qty in r.write_offs:
            write_offs.append(
                {**key, "write_off_date": days[t], "batch_no": batch_no, "qty": qty, "reason": "EXPIRY"}
            )
        for b in r.batches:
            if b.expiry is not None:
                batches.append(
                    {
                        "batch_id": uid("batch", it.store.code, it.product.sku, b.batch_no),
                        **key,
                        "batch_no": b.batch_no,
                        "qty": b.qty,
                        "expiry_date": b.expiry,
                    }
                )
        for d in r.open_orders:
            open_orders.append(
                {
                    **key,
                    "supplier_id": it.supplier.supplier_id,
                    "qty": d.qty,
                    "order_date": config.start_date + timedelta(days=d.order_day_index),
                    "expected_date": config.start_date + timedelta(days=d.day_index),
                }
            )
    write_csv(out, "stock_snapshots.csv", snapshots)
    write_csv(out, "receipts.csv", receipts)
    write_csv(out, "write_offs.csv", write_offs)
    write_csv(out, "batches.csv", batches)
    write_csv(out, "open_orders.csv", open_orders)


def _parse_scenarios(value: str) -> frozenset[int]:
    if value == "all":
        return ALL_SCENARIOS
    try:
        chosen = frozenset(int(v) for v in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid scenario list: {value}") from exc
    if not chosen <= ALL_SCENARIOS:
        raise argparse.ArgumentTypeError(f"scenarios must be within 1-5: {value}")
    return chosen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the RetailPilot AI synthetic dataset (CSV).")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="full")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--scenarios", type=_parse_scenarios, default=ALL_SCENARIOS, help='"all" or e.g. "1,3"'
    )
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 11, 2))
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/output"))
    args = parser.parse_args(argv)
    config = GeneratorConfig(
        profile=args.profile, seed=args.seed, end_date=args.end_date, scenarios=args.scenarios
    )
    manifest = generate(config, args.out)
    print(
        f"Synthetic dataset ({manifest['profile']}, seed {manifest['seed']}) written to {args.out.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
