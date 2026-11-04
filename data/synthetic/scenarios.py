"""The five demo scenarios of docs/04-demo-scenarios.md, planted with exact numbers.

Each scenario product has a constant daily demand (so the 28-day baseline equals it exactly, D-30), its own
dedicated supplier (so unrelated shortages cannot change the D-17 order-cost marking), and a final on-hand stock
chosen to produce the expected decision. Requirements use each store's window (A 3+2, B 7+2, C 5+3):

    requirement = ceil(d × (lead + review)) + ceil(d × safety) + min_display
"""

import math
from dataclasses import dataclass, field
from decimal import Decimal

from data.synthetic.catalog import STORES, Product, Supplier

WINDOW = {s.code: s.lead_time_days + s.review_period_days for s in STORES}


@dataclass(frozen=True, slots=True)
class Plant:
    """One store's planted position for a scenario product."""

    daily_demand: int
    safety_stock_days: int
    min_display_qty: int
    on_hand: int  # closing stock on the last day of history

    def requirement(self, store_code: str) -> int:
        d = self.daily_demand
        return (
            math.ceil(d * WINDOW[store_code]) + math.ceil(d * self.safety_stock_days) + self.min_display_qty
        )


@dataclass(slots=True)
class ScenarioProduct:
    product: Product
    plants: dict[str, Plant]
    final_batch_expiry_days: int | None = None  # days after the run date (scenario 5 near-dated batch)


@dataclass(slots=True)
class Scenario:
    number: int
    title: str
    supplier: Supplier
    products: dict[str, ScenarioProduct]
    expected: dict[str, object] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)


def _product(
    sku: str, name: str, category: str, cost: str, selling: str, pack: int, shelf: int | None
) -> Product:
    return Product(
        sku=sku,
        name=name,
        category=category,
        brand="Demo brand",
        cost_price=Decimal(cost),
        selling_price=Decimal(selling),
        order_pack_size=pack,
        shelf_life_days=shelf,
        base_rate=0.0,
    )


def build_scenarios(selected: frozenset[int]) -> list[Scenario]:
    all_scenarios = [
        Scenario(
            1,
            "Fast mover sells high in every store - PO only",
            Supplier("scenario-1", "Scenario supplier 1 (synthetic)"),
            {
                "main": ScenarioProduct(
                    _product("DEMO-RICE-5KG", "Rice 5 kg (demo)", "staples", "380", "450", 5, None),
                    {
                        "A": Plant(10, 1, 5, 30),  # requirement 65 → need 35
                        "B": Plant(8, 1, 5, 40),  # requirement 85 → need 45
                        "C": Plant(9, 1, 5, 35),  # requirement 86 → need 51
                    },
                )
            },
            {"po_needs": {"A": 35, "B": 45, "C": 51}},
        ),
        Scenario(
            2,
            "Surplus in Store A covers Store C - transfer, no PO",
            Supplier("scenario-2", "Scenario supplier 2 (synthetic)"),
            {
                "main": ScenarioProduct(
                    _product("DEMO-TEA-250G", "Tea 250 g (demo)", "beverages", "90", "120", 12, None),
                    {
                        "A": Plant(2, 1, 4, 46),  # requirement 16 → surplus 30
                        "B": Plant(2, 1, 4, 24),  # requirement 24 → exactly at requirement
                        "C": Plant(3, 1, 3, 10),  # requirement 30 → need 20
                    },
                )
            },
            {"transfer_qty": 20},
        ),
        Scenario(
            3,
            "Worked example - transfer 24 from A, PO 16 for C",
            Supplier("scenario-3", "Scenario supplier 3 (synthetic)"),
            {
                "main": ScenarioProduct(
                    _product("DEMO-BISCUIT-200G", "Biscuits 200 g (demo)", "biscuits", "25", "35", 24, None),
                    {
                        "A": Plant(4, 1, 6, 54),  # requirement 30 → surplus 24
                        "B": Plant(5, 1, 5, 55),  # requirement 55 → exactly at requirement (not short)
                        "C": Plant(4, 1, 4, 0),  # requirement 40 → need 40 (holds 0)
                    },
                )
            },
            {"transfer_qty": 24, "po_qty": 16},
        ),
        Scenario(
            4,
            "Bread reordered - butter co-replenished",
            Supplier("scenario-4", "Scenario supplier 4 (synthetic)"),
            {
                "bread": ScenarioProduct(
                    _product(
                        "DEMO-BREAD", "Bread 400 g (demo)", "bakery", "32", "40", 6, 14
                    ),  # long-life packaged: covers the B/C 9-day window plus delivery age
                    {
                        "A": Plant(10, 1, 8, 30),  # requirement 68 → need 38
                        "B": Plant(6, 1, 6, 66),  # requirement 66 → at requirement
                        "C": Plant(6, 1, 6, 60),  # requirement 60 → at requirement
                    },
                ),
                "butter": ScenarioProduct(
                    _product("DEMO-BUTTER-100G", "Butter 100 g (demo)", "dairy", "48", "58", 12, 21),
                    {
                        "A": Plant(3, 1, 4, 25),  # requirement 22, not short; 25 − 3 × 2 = 19 < 22 → +3
                        "B": Plant(2, 1, 4, 24),  # requirement 24 → at requirement
                        "C": Plant(2, 1, 4, 22),  # requirement 22 → at requirement
                    },
                ),
            },
            {"bread_po_qty": 38, "butter_co_replenish_qty": 3},
            {"store": "A"},
        ),
        Scenario(
            5,
            "Batch in Store A expires before A can sell it - expiry-aware transfer to C",
            Supplier("scenario-5", "Scenario supplier 5 (synthetic)"),
            {
                "main": ScenarioProduct(
                    _product("DEMO-PANEER-200G", "Paneer 200 g (demo)", "dairy", "80", "100", 6, 14),
                    {
                        "A": Plant(
                            2, 1, 2, 40
                        ),  # requirement 14; near-dated supply, last batch of 40 expires in 5 days
                        "B": Plant(2, 1, 2, 22),  # requirement 22 → at requirement
                        "C": Plant(8, 1, 2, 74),  # requirement 74 → at requirement; sells 8 / day
                    },
                    final_batch_expiry_days=5,
                )
            },
            {"at_risk": 30, "days_left": 5},
            {"from": "A", "to": "C"},
        ),
    ]
    return [s for s in all_scenarios if s.number in selected]
