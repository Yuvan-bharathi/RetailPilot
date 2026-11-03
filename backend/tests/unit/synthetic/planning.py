"""Rebuild nightly-run planning inputs from the synthetic CSVs using the real Phase 3 tools.

This mirrors what the Stock Balancing / Freshness agents will do (SD-04, SD-06, SD-07, SD-08), but reads the CSV
dataset instead of the database, so the planted scenarios can be checked before Phase 2/5 exist.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas as pd

from app.tools.forecast import ForecastTools
from app.tools.requirement import RequirementCalculator as RC
from app.tools.transfer_engine import TransferDecisionEngine as TE
from app.tools.types import CostInputs, Route, StoreState, StoreSupplyTerms, TransferPlan
from data.synthetic.reader import Dataset


class Planner:
    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.run_date = date.fromisoformat(ds.manifest["run_date"])
        self.end_date = date.fromisoformat(ds.manifest["end_date"])
        self.rules: dict[str, Any] = ds.business_rules

        lines = ds.sales_lines
        valid = lines.loc[~lines["is_voided"] & ~lines["is_return"] & (lines["qty"] > 0)]
        units = valid.groupby(["store_id", "product_id", "txn_date"])["qty"].sum()
        snaps = ds.stock_snapshots
        daily = snaps[["store_id", "product_id", "snapshot_date", "closing_on_hand"]].copy()
        keys = list(zip(daily["store_id"], daily["product_id"], daily["snapshot_date"], strict=True))
        daily["y"] = [float(units.get(k, 0)) for k in keys]
        daily["is_stockout"] = daily["closing_on_hand"] == 0
        daily["unique_id"] = [f"{s}:{p}" for s, p in zip(daily["store_id"], daily["product_id"], strict=True)]
        daily["ds"] = daily["snapshot_date"]
        self.daily = daily
        baseline = ForecastTools.baseline_avg_daily(daily[["unique_id", "ds", "y", "is_stockout"]])
        self._demand = dict(zip(baseline["unique_id"], baseline["daily_demand"], strict=True))

        last = snaps.loc[snaps["snapshot_date"] == self.end_date]
        self._on_hand = {
            (s, p): int(q)
            for s, p, q in zip(last["store_id"], last["product_id"], last["closing_on_hand"], strict=True)
        }
        grace = timedelta(days=int(self.rules["incoming_overdue_grace_days"]))
        self._incoming: dict[tuple[UUID, UUID], int] = {}
        for row in ds.open_orders.itertuples():
            if row.expected_date + grace >= self.run_date:
                key = (row.store_id, row.product_id)
                self._incoming[key] = self._incoming.get(key, 0) + int(row.qty)

        self._sp = {(r.store_id, r.product_id): r for r in ds.store_products.itertuples()}
        self._offer = {(r.supplier_id, r.product_id): r for r in ds.supplier_products.itertuples()}
        self._terms = {(r.supplier_id, r.store_id): r for r in ds.supplier_store_terms.itertuples()}
        self._supplier = {r.supplier_id: r for r in ds.suppliers.itertuples()}
        self._product = {r.product_id: r for r in ds.products.itertuples()}
        self.store_ids: list[UUID] = sorted(ds.stores["store_id"])

    # --- per store-product ------------------------------------------------------------------------------------

    def demand(self, store: UUID, product: UUID) -> float:
        return float(self._demand[f"{store}:{product}"])

    def preferred_supplier(self, store: UUID, product: UUID) -> UUID:
        supplier: UUID = self._sp[(store, product)].preferred_supplier_id
        return supplier

    def lead_time(self, store: UUID, product: UUID) -> int:
        supplier = self.preferred_supplier(store, product)
        terms = self._terms.get((supplier, store))
        offer = self._offer.get((supplier, product))
        return RC.lead_time(
            None if terms is None else int(terms.lead_time_days),
            None if offer is None else int(offer.lead_time_days),
            int(self._supplier[supplier].default_lead_time_days),
        )

    def requirement(self, store: UUID, product: UUID) -> int:
        sp = self._sp[(store, product)]
        return RC.own_requirement(
            self.demand(store, product),
            self.lead_time(store, product),
            int(sp.review_period_days),
            int(sp.safety_stock_days),
            int(sp.min_display_qty),
        )

    def available(self, store: UUID, product: UUID) -> int:
        return self._on_hand[(store, product)] + self._incoming.get((store, product), 0)

    def state(self, store: UUID, product: UUID) -> StoreState:
        return StoreState(
            store_id=store,
            requirement=self.requirement(store, product),
            available=self.available(store, product),
            daily_demand=self.demand(store, product),
            review_period_days=int(self._sp[(store, product)].review_period_days),
        )

    def states(self, product: UUID) -> list[StoreState]:
        return [
            self.state(s, product)
            for s in self.store_ids
            if (s, product) in self._sp and bool(self._sp[(s, product)].is_listed)
        ]

    def supply_terms(self, store: UUID, product: UUID) -> StoreSupplyTerms:
        supplier = self.preferred_supplier(store, product)
        return StoreSupplyTerms(
            supplier_id=supplier,
            lead_time_days=self.lead_time(store, product),
            delivery_charge=self._terms[(supplier, store)].delivery_charge,
            unit_cost=self._offer[(supplier, product)].price,
        )

    def unit_cost(self, store: UUID, product: UUID) -> Decimal:
        price: Decimal = self._offer[(self.preferred_supplier(store, product), product)].price
        return price

    # --- across stores ------------------------------------------------------------------------------------------

    def routes(self) -> dict[tuple[UUID, UUID], Route]:
        return {
            (r.from_store_id, r.to_store_id): Route(
                fixed_cost=r.fixed_cost,
                per_unit_cost=r.per_unit_cost,
                handling_cost_per_unit=r.handling_cost_per_unit,
                transit_days=int(r.transit_days),
            )
            for r in self.ds.transfer_routes.itertuples()
        }

    def planned_pairs(self) -> frozenset[tuple[UUID, UUID]]:
        """D-17 pass 1 over every product in the dataset."""
        products = sorted({p for _, p in self._sp})
        states_by_product = {p: self.states(p) for p in products}
        terms = {
            (s.store_id, p): self.supply_terms(s.store_id, p)
            for p, sts in states_by_product.items()
            for s in sts
        }
        return TE.mark_po_pairs(states_by_product, terms)

    def cost_inputs(self, product: UUID, planned: frozenset[tuple[UUID, UUID]]) -> CostInputs:
        shelf_life = self._product[product].shelf_life_days
        has_life = shelf_life is not None and not pd.isna(shelf_life)
        cap = int(shelf_life) if has_life else int(self.rules["days_to_sell_default_cap"])
        perishable = has_life and int(shelf_life) <= int(self.rules["perishable_max_shelf_life_days"])
        return CostInputs(
            terms_by_store={s.store_id: self.supply_terms(s.store_id, product) for s in self.states(product)},
            order_fixed_cost=Decimal(self.rules["order_fixed_cost"]),
            holding_cost_rate_per_day=Decimal(self.rules["holding_cost_rate_per_day"]),
            expiry_risk_pct=Decimal(self.rules["expiry_risk_pct"]),
            is_perishable=perishable,
            days_to_sell_cap=cap,
            planned_supplier_stores=planned,
        )

    def decide(self, product: UUID) -> TransferPlan:
        return TE.decide(
            product, self.states(product), self.routes(), self.cost_inputs(product, self.planned_pairs())
        )
