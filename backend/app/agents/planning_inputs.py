"""Shared, run-scoped planning inputs for the stock-balancing and freshness agents (SD-06/07/08, D-47).

Loaded once per agent with one query per table; every per-store-SKU figure follows spec §1:
- lead time of the supplier serving THAT store: store terms → supplier-product → supplier default (rule 1, D-05);
- own requirement = ceil(d × (lead + review)) + ceil(d × safety) + min display;
- available = shelf + backroom + incoming + pending lines of kept POs (D-14) − reserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.inventory import InventoryPosition
from app.domain.models.master import (
    Product,
    Store,
    StoreProduct,
    Supplier,
    SupplierProduct,
    SupplierStoreTerms,
)
from app.domain.models.planning import Forecast
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.repositories.purchasing_repo import PurchasingRepo
from app.domain.repositories.transfer_repo import TransferRepo
from app.domain.schemas.common import ProductRef, StoreRef, SupplierRef
from app.tools.requirement import RequirementCalculator
from app.tools.types import Route, StoreState, StoreSupplyTerms


@dataclass
class PlanningInputs:
    forecasts: dict[tuple[UUID, UUID], Forecast]
    positions: dict[tuple[UUID, UUID], InventoryPosition]
    listings: dict[tuple[UUID, UUID], StoreProduct]
    suppliers: dict[UUID, Supplier]
    offers: dict[tuple[UUID, UUID], SupplierProduct]
    terms: dict[tuple[UUID, UUID], SupplierStoreTerms]
    products: dict[UUID, Product]
    stores: dict[UUID, Store]
    routes: dict[tuple[UUID, UUID], Route]
    on_order_pending: dict[tuple[UUID, UUID], int]

    @classmethod
    def load(cls, session: Session, run_id: UUID, store_ids: list[UUID]) -> PlanningInputs:
        return cls(
            forecasts=PlanningRepo(session).get_forecasts_by_run(run_id),
            positions={
                (p.store_id, p.product_id): p
                for p in session.scalars(
                    select(InventoryPosition).where(InventoryPosition.store_id.in_(store_ids))
                )
            },
            listings={
                (sp.store_id, sp.product_id): sp
                for sp in session.scalars(select(StoreProduct).where(StoreProduct.store_id.in_(store_ids)))
                if sp.is_listed
            },
            suppliers={s.supplier_id: s for s in session.scalars(select(Supplier))},
            offers={(o.supplier_id, o.product_id): o for o in session.scalars(select(SupplierProduct))},
            terms={(t.supplier_id, t.store_id): t for t in session.scalars(select(SupplierStoreTerms))},
            products={p.product_id: p for p in session.scalars(select(Product))},
            stores={s.store_id: s for s in session.scalars(select(Store))},
            routes={
                key: Route(r.fixed_cost, r.per_unit_cost, r.handling_cost_per_unit, r.transit_days)
                for key, r in TransferRepo(session).get_route_matrix().items()
            },
            on_order_pending=PurchasingRepo(session).get_on_order_pending(store_ids),
        )

    # --- references ------------------------------------------------------------------------------------------

    def store_ref(self, store_id: UUID) -> StoreRef:
        return StoreRef(store_id=store_id, name=self.stores[store_id].name)

    def product_ref(self, product_id: UUID) -> ProductRef:
        p = self.products[product_id]
        return ProductRef(product_id=p.product_id, sku=p.sku, name=p.name, category=p.category)

    def supplier_ref(self, supplier_id: UUID) -> SupplierRef:
        return SupplierRef(supplier_id=supplier_id, name=self.suppliers[supplier_id].name)

    # --- per store-SKU -----------------------------------------------------------------------------------------

    def is_low_confidence(self, store_id: UUID, product_id: UUID) -> bool:
        fc = self.forecasts.get((store_id, product_id))
        return fc is not None and fc.confidence == "LOW"

    def demand(self, store_id: UUID, product_id: UUID) -> float:
        fc = self.forecasts.get((store_id, product_id))
        return fc.daily_demand if fc else 0.0

    def supplier_of(self, store_id: UUID, product_id: UUID) -> UUID | None:
        return self.listings[(store_id, product_id)].preferred_supplier_id

    def lead_time(self, store_id: UUID, product_id: UUID) -> int:
        supplier = self.supplier_of(store_id, product_id)
        term = self.terms.get((supplier, store_id)) if supplier else None
        offer = self.offers.get((supplier, product_id)) if supplier else None
        default = self.suppliers[supplier].default_lead_time_days if supplier in self.suppliers else 0
        return RequirementCalculator.lead_time(
            term.lead_time_days if term else None, offer.lead_time_days if offer else None, default
        )

    def state(self, store_id: UUID, product_id: UUID) -> StoreState:
        sp = self.listings[(store_id, product_id)]
        pos = self.positions.get((store_id, product_id))
        available = RequirementCalculator.available(
            pos.shelf_qty if pos else 0,
            pos.backroom_qty if pos else 0,
            (pos.incoming if pos else 0) + self.on_order_pending.get((store_id, product_id), 0),
            pos.reserved if pos else 0,
        )
        demand = self.demand(store_id, product_id)
        requirement = RequirementCalculator.own_requirement(
            demand,
            self.lead_time(store_id, product_id),
            sp.review_period_days,
            sp.safety_stock_days,
            sp.min_display_qty,
        )
        return StoreState(store_id, requirement, available, demand, sp.review_period_days)

    def supply_terms(self, store_id: UUID, product_id: UUID) -> StoreSupplyTerms | None:
        supplier = self.supplier_of(store_id, product_id)
        term = self.terms.get((supplier, store_id)) if supplier else None
        offer = self.offers.get((supplier, product_id)) if supplier else None
        if supplier is None or term is None or offer is None:
            return None
        return StoreSupplyTerms(
            supplier, self.lead_time(store_id, product_id), term.delivery_charge, offer.price
        )

    def unit_cost(self, store_id: UUID, product_id: UUID) -> Decimal:
        terms = self.supply_terms(store_id, product_id)
        return terms.unit_cost if terms else self.products[product_id].cost_price

    def receiver_states(self, product_id: UUID, exclude: UUID | None = None) -> list[StoreState]:
        """HIGH-confidence listed stores for a product (D-04), optionally without one store."""
        return [
            self.state(s, product_id)
            for (s, p) in sorted(self.listings, key=lambda k: str(k[0]))
            if p == product_id and s != exclude and not self.is_low_confidence(s, product_id)
        ]
