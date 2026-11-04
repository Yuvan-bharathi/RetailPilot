"""Export frontend mock fixtures from the synthetic `small` dataset, using the real Phase 3 tools.

Usage (from backend/):  uv run python -m scripts.export_mock_fixtures [--out ../frontend/src/mocks/data/fixtures.json]

Steps, in nightly-run order: generate the dataset (fixed seed) → baseline forecasts (D-30) → stale SKUs are
low-confidence (D-04) → D-17 pass 1 marking → transfer-vs-PO decisions by urgency (SD-06/07) → co-replenishment
(D-02/D-13) → expiry risk and expiry-aware transfers (SD-08, D-28, D-31) → consolidated draft POs (SD-09).
Every object is built as a backend DTO (so the JSON always matches the API contract) and the five demo scenarios
are asserted before writing.
"""

import argparse
import json
import math
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pandas as pd
from pydantic import TypeAdapter

from app.domain.schemas.common import Counterpart, ProductRef, StoreRef, SupplierRef
from app.domain.schemas.dtos import (
    BatchDTO,
    BatchRiskRef,
    CoReplenishEvidence,
    DashboardSummary,
    Evidence,
    ExpiryEvidence,
    InventoryMovementDTO,
    InventoryRowDTO,
    MoverDTO,
    NeedsReviewEvidence,
    POLineDTO,
    PurchaseOrderDTO,
    RecommendationDTO,
    ReorderEvidence,
    RunInfoDTO,
    StoreDTO,
    TransferEvidence,
    TransferOrderDTO,
)
from app.tools.basket import BasketTools
from app.tools.freshness import FreshnessTools
from app.tools.lost_sales import LostSalesCalculator
from app.tools.numeric import money
from app.tools.po_builder import POBuilder
from app.tools.requirement import RequirementCalculator as RC
from app.tools.transfer_engine import TransferDecisionEngine as TE
from app.tools.types import (
    BasketQualityRules,
    BatchInfo,
    PONeed,
    ReplenishmentNeed,
    StoreState,
    SupplierOffer,
    TransferProposal,
)
from data.synthetic.catalog import NAMESPACE
from data.synthetic.config import GeneratorConfig
from data.synthetic.generate import generate
from data.synthetic.reader import Dataset, load_dataset
from scripts.planning import Planner

BACKGROUND_PRODUCTS = 50
MOVEMENT_DAYS = 11
NEAR_EXPIRY_DAYS = 7
EVIDENCE = TypeAdapter(Evidence)
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "mocks" / "data" / "fixtures.json"


def uid(*parts: object) -> UUID:
    return uuid5(NAMESPACE, "mock/" + "/".join(str(p) for p in parts))


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


@dataclass
class Rec:
    dto: RecommendationDTO
    evidence: Any  # one of the Evidence models


@dataclass
class Builder:
    ds: Dataset
    pl: Planner
    products: list[UUID]
    stale: set[tuple[UUID, UUID]]
    run_id: UUID
    created: datetime
    recs: list[Rec] = field(default_factory=list)
    transfers: list[TransferOrderDTO] = field(default_factory=list)
    needs: list[tuple[PONeed, UUID | None]] = field(default_factory=list)  # (need, rec_id)

    # --- refs ----------------------------------------------------------------------------------------------------

    def store_ref(self, store: UUID) -> StoreRef:
        row = self.ds.stores.loc[self.ds.stores["store_id"] == store].iloc[0]
        return StoreRef(store_id=store, name=str(row["name"]))

    def product_ref(self, product: UUID) -> ProductRef:
        p = self.pl.product(product)
        return ProductRef(product_id=product, sku=str(p.sku), name=str(p.name), category=str(p.category))

    def supplier_ref(self, supplier: UUID) -> SupplierRef:
        return SupplierRef(supplier_id=supplier, name=self.pl.supplier_name(supplier))

    def add_rec(self, **kwargs: Any) -> UUID:
        evidence = kwargs.pop("evidence")
        rec_id = uid(
            "rec", len(self.recs), kwargs["rec_type"], kwargs["store"].store_id, kwargs["product"].product_id
        )
        dto = RecommendationDTO(rec_id=rec_id, run_id=self.run_id, created_at=self.created, **kwargs)
        self.recs.append(Rec(dto, evidence))
        return rec_id


def _lost_sales(pl: Planner, run_date: date, lookback: int) -> pd.DataFrame:
    window = pl.daily.loc[pl.daily["snapshot_date"] > run_date - timedelta(days=lookback + 1)]
    daily = window.rename(columns={"snapshot_date": "day", "y": "units"})[
        ["store_id", "product_id", "day", "units"]
    ]
    stockouts = window.loc[window["is_stockout"], ["store_id", "product_id", "snapshot_date"]].rename(
        columns={"snapshot_date": "day"}
    )
    margins = pd.DataFrame(
        [
            {
                "product_id": p,
                "selling_price": pl.product(p).selling_price,
                "unit_margin": pl.product(p).selling_price - pl.product(p).cost_price,
            }
            for p in pl.listed_products()
        ]
    )
    return LostSalesCalculator.estimate(daily, stockouts, margins).set_index(["store_id", "product_id"])


def _select_products(ds: Dataset) -> list[UUID]:
    scenario = [UUID(p) for p in ds.manifest["scenario_product_ids"]]
    lines = ds.sales_lines.loc[~ds.sales_lines["is_voided"] & ~ds.sales_lines["is_return"]]
    revenue = (lines["qty"] * lines["unit_price"].astype(float)).groupby(lines["product_id"]).sum()
    background = [p for p in revenue.sort_values(ascending=False, kind="stable").index if p not in scenario]
    return scenario + sorted(background[:BACKGROUND_PRODUCTS], key=str)


def _stale(ds: Dataset, pl: Planner, run_date: date) -> set[tuple[UUID, UUID]]:
    stale_days = int(ds.business_rules["stale_days"])
    sold = pl.daily.loc[pl.daily["y"] > 0].groupby(["store_id", "product_id"])["snapshot_date"].max()
    out: set[tuple[UUID, UUID]] = set()
    for (store, product), last in sold.items():
        if (run_date - last).days > stale_days and pl.on_hand(store, product) > 0:
            out.add((store, product))
    return out


def _states(b: Builder, product: UUID) -> list[StoreState]:
    return [s for s in b.pl.states(product) if (s.store_id, product) not in b.stale]


# --- stock balancing (SD-06/07) -------------------------------------------------------------------------------------


def _balance(b: Builder, lost: pd.DataFrame) -> None:
    pl = b.pl
    states_by_product = {p: _states(b, p) for p in pl.listed_products()}
    supply = {
        (s.store_id, p): pl.supply_terms(s.store_id, p) for p, sts in states_by_product.items() for s in sts
    }
    planned = set(TE.mark_po_pairs(states_by_product, supply))

    # low-confidence store-SKUs that are short → NEEDS_REVIEW, never automatic (D-04)
    for store, product in sorted(b.stale, key=str):
        if product not in b.products:
            continue
        state = pl.state(store, product)
        if state.available < state.requirement:
            b.add_rec(
                store=b.store_ref(store),
                product=b.product_ref(product),
                rec_type="REORDER",
                status="NEEDS_REVIEW",
                priority="NORMAL",
                qty=state.requirement - state.available,
                explanation="No recent sales while stock is held, so the forecast is unreliable. Please review.",
                evidence=NeedsReviewEvidence(
                    kind="NEEDS_REVIEW",
                    reason="LOW_CONFIDENCE",
                    own_requirement=state.requirement,
                    available=state.available,
                    suggested_qty=state.requirement - state.available,
                    detail=f"No sales for more than {b.ds.business_rules['stale_days']} days while stock is held.",
                ),
            )

    def urgency(p: UUID) -> tuple[float, str]:
        short = [s.days_of_cover for s in states_by_product[p] if s.available < s.requirement]
        return (min(short) if short else math.inf, str(p))

    for product in sorted(b.products, key=urgency):
        states = states_by_product[product]
        if not any(s.available < s.requirement for s in states):
            continue
        plan = TE.decide(product, states, pl.routes(), pl.cost_inputs(product, frozenset(planned)))
        by_store = {s.store_id: s for s in states}
        remainder = {n.store_id: n.qty for n in plan.po_needs}
        for t in plan.transfers:
            _transfer_rec(b, t, by_store[t.to_store], remainder.get(t.to_store, 0))
        for need in plan.po_needs:
            rec_id = _reorder_rec(b, need, by_store[need.store_id], lost)
            b.needs.append((need, rec_id))
            planned.add((need.supplier_id, need.store_id))


def _transfer_rec(b: Builder, t: TransferProposal, short: StoreState, po_remainder: int) -> None:
    pl = b.pl
    demand = max(short.daily_demand, 0.01)
    evidence = TransferEvidence(
        kind="TRANSFER",
        destination_shortage=int(t.evidence["need"]),  # type: ignore[call-overload]
        donor=Counterpart(store=b.store_ref(t.from_store), qty=t.qty),
        donor_surplus=int(t.evidence["donor_surplus"]),  # type: ignore[call-overload]
        donor_protected_requirement=int(t.evidence["donor_requirement"]),  # type: ignore[call-overload]
        donor_keeps_requirement=True,
        transfer_qty=t.qty,
        po_remainder_qty=po_remainder,
        transfer_cost=t.transfer_cost,
        po_incremental_cost=t.po_cost_avoided,
        expected_delivery=pl.run_date + timedelta(days=t.transit_days),
        days_of_cover_before=round(short.available / demand, 1),
        days_of_cover_after=round((short.available + t.qty) / demand, 1),
    )
    donor = b.store_ref(t.from_store).name
    rec_id = b.add_rec(
        store=b.store_ref(t.to_store),
        product=b.product_ref(t.product_id),
        rec_type="TRANSFER",
        status="PENDING",
        priority=TE._priority(short, pl.lead_time(t.to_store, t.product_id)),
        qty=t.qty,
        counterpart=Counterpart(store=b.store_ref(t.from_store), qty=t.qty),
        explanation=(
            f"Transfer {t.qty} units from {donor}, which holds more than it needs before its next delivery"
            + (f"; order the remaining {po_remainder} from the supplier." if po_remainder else ".")
        ),
        evidence=evidence,
    )
    b.transfers.append(
        TransferOrderDTO(
            transfer_id=uid("transfer", rec_id),
            product=b.product_ref(t.product_id),
            from_store=b.store_ref(t.from_store),
            to_store=b.store_ref(t.to_store),
            qty=t.qty,
            status="PROPOSED",
            is_expiry_aware="days_left" in t.evidence,
            transit_days=t.transit_days,
            transfer_cost=t.transfer_cost,
            created_at=b.created,
            received_qty=None,
        )
    )


def _reorder_rec(b: Builder, need: PONeed, state: StoreState, lost: pd.DataFrame) -> UUID:
    pl = b.pl
    sp = pl.store_product(need.store_id, need.product_id)
    key = (need.store_id, need.product_id)
    # no lost sales → null (shown as "—"), not ₹0.00
    lost_revenue = (
        lost.loc[key, "lost_revenue"] if key in lost.index and lost.loc[key, "lost_revenue"] > 0 else None
    )
    lost_profit = (
        lost.loc[key, "lost_profit"] if key in lost.index and lost.loc[key, "lost_profit"] > 0 else None
    )
    reason_text = {
        "NO_SURPLUS_IN_ANY_STORE": "No other store has stock to spare",
        "PARTIAL_SURPLUS": "Other stores could cover only part of the need",
        "TRANSFER_NOT_VIABLE": "A transfer would cost more or arrive later than a supplier delivery",
    }[need.reason]
    return b.add_rec(
        store=b.store_ref(need.store_id),
        product=b.product_ref(need.product_id),
        rec_type="REORDER",
        status="PENDING",
        priority=need.priority,
        qty=need.qty,
        lost_revenue=lost_revenue,
        explanation=f"Order {need.qty} units. {reason_text}.",
        evidence=ReorderEvidence(
            kind="REORDER",
            reason=need.reason,  # type: ignore[arg-type]
            daily_demand=round(state.daily_demand, 3),
            lead_time_days=pl.lead_time(need.store_id, need.product_id),
            review_period_days=int(sp.review_period_days),
            safety_stock_days=int(sp.safety_stock_days),
            min_display_qty=int(sp.min_display_qty),
            own_requirement=state.requirement,
            available=state.available,
            need_qty=state.requirement - state.available,
            transferred_qty=int(need.evidence["transferred_qty"]),  # type: ignore[call-overload]
            days_of_cover=round(state.days_of_cover, 1),
            supplier=b.supplier_ref(need.supplier_id),
            lost_revenue=lost_revenue,
            lost_profit=lost_profit,
        ),
    )


# --- co-replenishment (D-02, D-13) ----------------------------------------------------------------------------------


def _store_rules(b: Builder, store: UUID) -> pd.DataFrame:
    rules = b.ds.business_rules["basket"]
    lines = b.ds.sales_lines
    recent = lines.loc[
        (lines["store_id"] == store) & (lines["txn_date"] > b.pl.end_date - timedelta(days=90))
    ]
    cleaned = BasketTools.clean_bills(
        recent,
        BasketQualityRules(
            max_qty_per_line=int(rules["max_qty_per_line"]),
            exclude_promo_days=bool(rules["exclude_promo_days"]),
        ),
    )
    return BasketTools.mine_rules(
        BasketTools.to_basket_matrix(cleaned),
        min_support=float(rules["min_support"]),
        min_confidence=float(rules["min_confidence"]),
        min_lift=float(rules["min_lift"]),
    )


def _co_replenish(b: Builder) -> None:
    pl = b.pl
    co = b.ds.business_rules["co_replenish"]
    delivering = {(n.supplier_id, n.store_id) for n, _ in b.needs}
    existing = {(n.store_id, n.product_id) for n, _ in b.needs}
    rules_by_store = {s: _store_rules(b, s) for s in pl.store_ids}
    for need, _ in list(b.needs):
        rules = rules_by_store[need.store_id]
        complements = rules.loc[
            (rules["antecedent_id"] == need.product_id) & (rules["lift"] >= float(co["min_lift"]))
        ].head(int(co["limit"]))
        for rule in complements.itertuples():
            product = rule.consequent_id
            key = (need.store_id, product)
            if key in b.stale or key in existing:
                continue  # D-02: an existing need is linked, never duplicated (no second recommendation)
            state = pl.state(need.store_id, product)
            qty = RC.co_replenish_qty(
                state.available, state.daily_demand, state.review_period_days, state.requirement
            )
            supplier = pl.preferred_supplier(need.store_id, product)
            if qty <= 0 or (supplier, need.store_id) not in delivering:
                continue
            linked = b.product_ref(need.product_id)
            rec_id = b.add_rec(
                store=b.store_ref(need.store_id),
                product=b.product_ref(product),
                rec_type="CO_REPLENISH",
                status="PENDING",
                priority="NORMAL",
                qty=qty,
                explanation=(
                    f"Add {qty} units to the {pl.supplier_name(supplier)} order: it is bought with "
                    f"{linked.name} (lift {float(rule.lift):.1f}) and would fall below its requirement before the "
                    "next review."
                ),
                evidence=CoReplenishEvidence(
                    kind="CO_REPLENISH",
                    linked_product=linked,
                    support=round(float(rule.support), 4),
                    confidence=round(float(rule.confidence), 3),
                    lift=round(float(rule.lift), 2),
                    daily_demand=round(state.daily_demand, 3),
                    review_period_days=state.review_period_days,
                    own_requirement=state.requirement,
                    available=state.available,
                    projected_at_next_review=round(
                        state.available - state.daily_demand * state.review_period_days, 2
                    ),
                    supplier=b.supplier_ref(supplier),
                ),
            )
            b.needs.append(
                (
                    PONeed(
                        store_id=need.store_id,
                        product_id=product,
                        qty=qty,
                        priority="NORMAL",
                        reason="CO_REPLENISH",
                        supplier_id=supplier,
                    ),
                    rec_id,
                )
            )
            existing.add(key)


# --- freshness (SD-08) ------------------------------------------------------------------------------------------------


def _batch_infos(b: Builder, store: UUID, product: UUID) -> list[tuple[Any, BatchInfo]]:
    rows = b.ds.batches.loc[(b.ds.batches["store_id"] == store) & (b.ds.batches["product_id"] == product)]
    return [(r, BatchInfo(r.batch_id, int(r.qty), r.expiry_date)) for r in rows.itertuples()]


def _freshness(b: Builder) -> None:
    pl = b.pl
    window = int(b.ds.business_rules["expiry_window_days"])
    for store in pl.store_ids:
        for product in b.products:
            batches = [
                (r, i)
                for r, i in _batch_infos(b, store, product)
                if (i.expiry_date - pl.run_date).days <= window
            ]
            if not batches:
                continue
            risks = FreshnessTools.at_risk_by_batch(
                [i for _, i in batches], pl.demand(store, product), pl.run_date
            )
            rows = {i.batch_id: r for r, i in batches}
            for risk in risks:
                if risk.at_risk <= 0:
                    continue
                ref = BatchRiskRef(
                    batch_no=str(rows[risk.batch_id].batch_no),
                    expiry_date=risk.expiry_date,
                    days_left=risk.days_left,
                    batch_qty=risk.qty,
                    at_risk_qty=risk.at_risk,
                )
                states = [s for s in _states(b, product) if s.store_id != store]
                receivers = TE.find_expiry_receivers(
                    product,
                    risk.at_risk,
                    risk.days_left,
                    store,
                    states,
                    pl.routes(),
                    pl.unit_cost(store, product),
                )
                left = risk.at_risk
                for t in receivers:
                    left -= t.qty
                    receiver = next(s for s in states if s.store_id == t.to_store)
                    rec_id = b.add_rec(
                        store=b.store_ref(t.to_store),
                        product=b.product_ref(product),
                        rec_type="TRANSFER",
                        status="PENDING",
                        priority="HIGH",
                        qty=t.qty,
                        counterpart=Counterpart(store=b.store_ref(store), qty=t.qty),
                        explanation=(
                            f"{b.store_ref(store).name} cannot sell batch {ref.batch_no} before it expires in "
                            f"{ref.days_left} days; this store sells it fast enough. Transfer {t.qty} units."
                        ),
                        evidence=TransferEvidence(
                            kind="TRANSFER",
                            destination_shortage=0,
                            donor=Counterpart(store=b.store_ref(store), qty=t.qty),
                            donor_surplus=risk.at_risk,
                            donor_protected_requirement=pl.requirement(store, product),
                            donor_keeps_requirement=True,
                            transfer_qty=t.qty,
                            po_remainder_qty=0,
                            transfer_cost=t.transfer_cost,
                            po_incremental_cost=None,
                            expected_delivery=pl.run_date + timedelta(days=t.transit_days),
                            days_of_cover_before=round(receiver.days_of_cover, 1),
                            days_of_cover_after=round(
                                (receiver.available + t.qty) / max(receiver.daily_demand, 0.01), 1
                            ),
                            expiring_batch=ref,
                        ),
                    )
                    b.transfers.append(
                        TransferOrderDTO(
                            transfer_id=uid("transfer", rec_id),
                            product=b.product_ref(product),
                            from_store=b.store_ref(store),
                            to_store=b.store_ref(t.to_store),
                            qty=t.qty,
                            status="PROPOSED",
                            is_expiry_aware=True,
                            transit_days=t.transit_days,
                            transfer_cost=t.transfer_cost,
                            created_at=b.created,
                            received_qty=None,
                        )
                    )
                if left > 0:
                    b.add_rec(
                        store=b.store_ref(store),
                        product=b.product_ref(product),
                        rec_type="EXPIRY_ALERT",
                        status="PENDING",
                        priority="HIGH" if ref.days_left <= 3 else "NORMAL",
                        qty=left,
                        lost_revenue=money(left * pl.product(product).selling_price),
                        explanation=(
                            f"{left} units of batch {ref.batch_no} will expire in {ref.days_left} days and no other "
                            "store can sell them in time."
                        ),
                        evidence=ExpiryEvidence(
                            kind="EXPIRY",
                            batch=ref.model_copy(update={"at_risk_qty": left}),
                            daily_demand=round(pl.demand(store, product), 3),
                            receivers_checked=len(states),
                        ),
                    )


# --- purchase orders (SD-09) -------------------------------------------------------------------------------------------


def _purchase_orders(b: Builder) -> list[PurchaseOrderDTO]:
    pl = b.pl
    offers_by_product: dict[UUID, list[Any]] = defaultdict(list)
    for r in b.ds.supplier_products.itertuples():
        offers_by_product[r.product_id].append(r)
    assigned = []
    for need, rec_id in b.needs:
        lead = pl.lead_time(need.store_id, need.product_id)
        offers = [
            SupplierOffer(
                supplier_id=r.supplier_id,
                product_id=r.product_id,
                unit_price=r.price,
                lead_time_days=lead if r.supplier_id == need.supplier_id else int(r.lead_time_days),
                moq=int(r.moq),
                order_pack_size=int(r.order_pack_size),
            )
            for r in offers_by_product[need.product_id]
        ]
        replenishment = ReplenishmentNeed(
            store_id=need.store_id,
            product_id=need.product_id,
            qty=need.qty,
            run_date=pl.run_date,
            required_by=pl.run_date + timedelta(days=lead),
            priority=need.priority,
            reason=need.reason,
            preferred_supplier_id=need.supplier_id,
            source_rec_id=rec_id,
        )
        offer = POBuilder.select_supplier(replenishment, offers, replenishment.required_by)
        if offer is not None:
            assigned.append((replenishment, offer))
    threshold = Decimal(b.ds.business_rules["po_l2_threshold"])
    out: list[PurchaseOrderDTO] = []
    for draft in POBuilder.consolidate(assigned):
        lines = []
        for line in draft.lines:
            qty = POBuilder.round_to_pack(line.qty, line.order_pack_size, line.moq)
            lines.append(
                POLineDTO(
                    po_line_id=uid("po-line", draft.supplier_id, line.store_id, line.product_id),
                    store=b.store_ref(line.store_id),
                    product=b.product_ref(line.product_id),
                    qty=qty,
                    unit_price=line.unit_price,
                    line_value=money(line.unit_price * qty),
                    line_status="PENDING",
                )
            )
        total = money(sum((line.unit_price * line.qty for line in lines), Decimal(0)))
        out.append(
            PurchaseOrderDTO(
                po_id=uid("po", draft.supplier_id),
                supplier=b.supplier_ref(draft.supplier_id),
                status="PENDING_L1",
                required_level="L2" if total >= threshold else "L1",
                total_value=total,
                l1_deadline=b.created + timedelta(hours=int(b.ds.business_rules["l1_deadline_hours"])),
                parent_po_id=None,
                flags=[],
                lines=lines,
                other_store_lines=[],
                created_at=b.created,
            )
        )
    return out


# --- inventory, movements, batches ---------------------------------------------------------------------------------


def _inventory(b: Builder) -> dict[str, list[dict[str, Any]]]:
    pl = b.pl
    pending_in: dict[tuple[UUID, UUID], int] = defaultdict(int)
    pending_out: dict[tuple[UUID, UUID], int] = defaultdict(int)
    for t in b.transfers:
        pending_in[(t.to_store.store_id, t.product.product_id)] += t.qty
        pending_out[(t.from_store.store_id, t.product.product_id)] += t.qty
    last = b.ds.stock_snapshots.loc[b.ds.stock_snapshots["snapshot_date"] == pl.end_date]
    snap = {(r.store_id, r.product_id): r for r in last.itertuples()}
    out: dict[str, list[dict[str, Any]]] = {}
    for store in pl.store_ids:
        rows = []
        for product in b.products:
            s = snap[(store, product)]
            sp = pl.store_product(store, product)
            demand = pl.demand(store, product)
            available = pl.available(store, product)
            requirement = pl.requirement(store, product)
            lead = pl.lead_time(store, product)
            cover = available / max(demand, 0.01)
            risk = (
                "HIGH" if cover < lead else "MEDIUM" if cover < lead + int(sp.review_period_days) else "LOW"
            )
            near = sum(
                i.qty
                for _, i in _batch_infos(b, store, product)
                if (i.expiry_date - pl.run_date).days <= NEAR_EXPIRY_DAYS
            )
            rows.append(
                InventoryRowDTO(
                    product=b.product_ref(product),
                    shelf_qty=int(s.shelf_qty),
                    shelf_min=int(sp.min_display_qty),
                    backroom_qty=int(s.backroom_qty),
                    incoming=pl.incoming(store, product),
                    reserved=0,
                    available=available,
                    own_requirement=requirement,
                    surplus_or_shortage=available - requirement,
                    days_of_cover=round(min(cover, 999.0), 1),
                    stockout_risk=risk,  # type: ignore[arg-type]
                    near_expiry_qty=near,
                    pending_transfer_in=pending_in[(store, product)],
                    pending_transfer_out=pending_out[(store, product)],
                    refill_from_backroom=int(s.shelf_qty) < int(sp.min_display_qty)
                    and int(s.backroom_qty) > 0,
                ).model_dump(mode="json")
            )
        out[str(store)] = rows
    return out


def _movements(b: Builder) -> dict[str, list[dict[str, Any]]]:
    pl, ds = b.pl, b.ds
    start = pl.end_date - timedelta(days=MOVEMENT_DAYS - 1)
    selected = set(b.products)
    out: dict[str, list[dict[str, Any]]] = {str(s): [] for s in pl.store_ids}

    def add(
        store: UUID,
        product: UUID,
        mtype: str,
        qty: int,
        location: str,
        ref: str | None,
        reason: str | None,
        when: datetime,
    ) -> None:
        dto = InventoryMovementDTO(
            movement_id=uid("move", store, product, mtype, when.isoformat(), ref, qty),
            product=b.product_ref(product),
            movement_type=mtype,  # type: ignore[arg-type]
            qty=qty,
            location=location,  # type: ignore[arg-type]
            reference=ref,
            reason=reason,
            created_at=when,
        )
        out[str(store)].append(dto.model_dump(mode="json"))

    daily = pl.daily.loc[(pl.daily["snapshot_date"] >= start) & (pl.daily["y"] > 0)]
    for r in daily.itertuples():
        if r.product_id in selected:
            add(
                r.store_id,
                r.product_id,
                "SALE",
                -int(r.y),
                "SHELF",
                f"POS bills {r.snapshot_date.isoformat()}",
                None,
                at(r.snapshot_date, 15, 30),
            )
    for r in ds.receipts.loc[ds.receipts["receipt_date"] >= start].itertuples():
        if r.product_id in selected:
            add(
                r.store_id,
                r.product_id,
                "PO_RECEIPT",
                int(r.qty),
                "BACKROOM",
                f"Batch {r.batch_no}",
                "Supplier delivery",
                at(r.receipt_date, 4, 30),
            )
    for r in ds.write_offs.loc[ds.write_offs["write_off_date"] >= start].itertuples():
        if r.product_id in selected:
            add(
                r.store_id,
                r.product_id,
                "EXPIRY_WRITE_OFF",
                -int(r.qty),
                "BACKROOM",
                f"Batch {r.batch_no}",
                "Expired",
                at(r.write_off_date, 2, 0),
            )
    mismatch = ds.manifest["edge_cases"]["stock_mismatch"]
    day = date.fromisoformat(mismatch["date"])
    if day >= start and UUID(mismatch["product_id"]) in selected:
        add(
            UUID(mismatch["store_id"]),
            UUID(mismatch["product_id"]),
            "ADJUSTMENT",
            int(mismatch["delta"]),
            "BACKROOM",
            "Reconciliation",
            "POS stock count lower than the ledger",
            at(day + timedelta(days=1), 0, 5),
        )
    for rows in out.values():
        rows.sort(key=lambda m: (m["created_at"], m["product"]["sku"], m["movement_type"]), reverse=True)
    return out


def _batches(b: Builder) -> dict[str, list[dict[str, Any]]]:
    pl = b.pl
    out: dict[str, list[dict[str, Any]]] = {}
    for store in pl.store_ids:
        rows = []
        for product in b.products:
            infos = _batch_infos(b, store, product)
            if not infos:
                continue
            risks = FreshnessTools.at_risk_by_batch(
                [i for _, i in infos], pl.demand(store, product), pl.run_date
            )
            by_id = {i.batch_id: r for r, i in infos}
            for rank, risk in enumerate(risks, start=1):
                rows.append(
                    BatchDTO(
                        batch_id=risk.batch_id,
                        product=b.product_ref(product),
                        batch_no=str(by_id[risk.batch_id].batch_no),
                        qty=risk.qty,
                        expiry_date=risk.expiry_date,
                        days_left=risk.days_left,
                        fefo_rank=rank,
                        at_risk_qty=risk.at_risk,
                    ).model_dump(mode="json")
                )
        rows.sort(key=lambda r: (r["expiry_date"], r["product"]["sku"], r["fefo_rank"]))
        out[str(store)] = rows
    return out


# --- dashboard -----------------------------------------------------------------------------------------------------------


def _dashboard(
    b: Builder,
    lost: pd.DataFrame,
    inventory: dict[str, list[dict[str, Any]]],
    pos: Sequence[PurchaseOrderDTO],
) -> dict[str, Any]:
    pl, ds = b.pl, b.ds
    start = pl.end_date - timedelta(days=27)
    lines = ds.sales_lines.loc[
        ~ds.sales_lines["is_voided"] & ~ds.sales_lines["is_return"] & (ds.sales_lines["txn_date"] >= start)
    ]
    out: dict[str, Any] = {}
    for key in [None, *pl.store_ids]:
        scope = lines if key is None else lines.loc[lines["store_id"] == key]
        revenue = sum(
            (q * p - d for q, p, d in zip(scope["qty"], scope["unit_price"], scope["discount"], strict=True)),
            Decimal(0),
        )
        cost = sum(
            (q * pl.product(p).cost_price for q, p in zip(scope["qty"], scope["product_id"], strict=True)),
            Decimal(0),
        )
        window = pl.daily.loc[pl.daily["snapshot_date"] >= start]
        window = window if key is None else window.loc[window["store_id"] == key]
        lost_scope = lost if key is None else lost.loc[[k for k in lost.index if k[0] == key]]
        stores = pl.store_ids if key is None else [key]
        inv_value = sum(
            (pl.on_hand(s, p) * pl.product(p).cost_price for s in stores for p in pl.listed_products()),
            Decimal(0),
        )
        near_value = sum(
            (
                Decimal(r["near_expiry_qty"]) * pl.product(UUID(r["product"]["product_id"])).cost_price
                for s in stores
                for r in inventory[str(s)]
            ),
            Decimal(0),
        )
        units = scope.groupby("product_id")["qty"].sum().sort_values(ascending=False, kind="stable")
        rev_by = {
            p: sum((q * pr for q, pr in zip(g["qty"], g["unit_price"], strict=True)), Decimal(0))
            for p, g in scope.groupby("product_id")
        }

        def movers(ids: list[Any], units: Any = units, rev_by: dict[Any, Decimal] = rev_by) -> list[MoverDTO]:
            return [
                MoverDTO(product=b.product_ref(p), units=int(units[p]), revenue=money(rev_by[p])) for p in ids
            ]

        recs = [r for r in b.recs if key is None or r.dto.store.store_id == key]
        dto = DashboardSummary(
            store=None if key is None else b.store_ref(key),
            period="LAST_28_DAYS",
            revenue=money(revenue),
            gross_profit=money(revenue - cost),
            margin_pct=round(float((revenue - cost) / revenue), 4) if revenue else 0.0,
            stockout_rate=round(float(window["is_stockout"].mean()), 4),
            lost_revenue=money(sum(lost_scope["lost_revenue"], Decimal(0))),
            lost_profit=money(sum(lost_scope["lost_profit"], Decimal(0))),
            inventory_value=money(inv_value),
            near_expiry_value=money(near_value),
            pending_recommendations=sum(1 for r in recs if r.dto.status in ("PENDING", "NEEDS_REVIEW")),
            pending_purchase_orders=sum(
                1 for po in pos if key is None or any(line.store.store_id == key for line in po.lines)
            ),
            active_transfers=sum(
                1 for t in b.transfers if key is None or key in (t.from_store.store_id, t.to_store.store_id)
            ),
            fast_movers=movers(list(units.index[:3])),
            slow_movers=movers(list(units.index[-3:][::-1])),
        )
        out["all" if key is None else str(key)] = dto.model_dump(mode="json")
    return out


# --- scenarios -------------------------------------------------------------------------------------------------------------


def _scenarios(b: Builder) -> dict[str, Any]:
    m = b.ds.manifest
    code = {UUID(v): k for k, v in m["stores"].items()}

    def recs(product: str, rec_type: str | None = None) -> list[Rec]:
        return [
            r
            for r in b.recs
            if str(r.dto.product.product_id) == product and (rec_type is None or r.dto.rec_type == rec_type)
        ]

    out: dict[str, Any] = {}
    s = m["scenarios"]
    one = recs(s["1"]["product_id"])
    assert all(r.dto.rec_type == "REORDER" for r in one), "scenario 1: PO only"
    assert {code[r.dto.store.store_id]: r.dto.qty for r in one} == s["1"]["expected"]["po_needs"], (
        "scenario 1 qty"
    )
    out["1"] = {
        "title": s["1"]["title"],
        "product_id": s["1"]["product_id"],
        "rec_ids": [str(r.dto.rec_id) for r in one],
    }

    two = recs(s["2"]["product_id"])
    assert [(r.dto.rec_type, code[r.dto.store.store_id], r.dto.qty) for r in two] == [
        ("TRANSFER", "C", 20)
    ], "scenario 2"
    out["2"] = {
        "title": s["2"]["title"],
        "product_id": s["2"]["product_id"],
        "rec_ids": [str(r.dto.rec_id) for r in two],
    }

    three = recs(s["3"]["product_id"])
    got = sorted((r.dto.rec_type, code[r.dto.store.store_id], r.dto.qty) for r in three)
    assert got == [("REORDER", "C", 16), ("TRANSFER", "C", 24)], f"scenario 3: {got}"
    out["3"] = {
        "title": s["3"]["title"],
        "product_id": s["3"]["product_id"],
        "rec_ids": [str(r.dto.rec_id) for r in three],
    }

    bread = recs(s["4"]["bread_id"], "REORDER")
    butter = recs(s["4"]["butter_id"], "CO_REPLENISH")
    assert [(code[r.dto.store.store_id], r.dto.qty) for r in bread] == [("A", 38)], "scenario 4 bread"
    assert [(code[r.dto.store.store_id], r.dto.qty) for r in butter] == [("A", 3)], "scenario 4 butter"
    out["4"] = {
        "title": s["4"]["title"],
        "product_id": s["4"]["bread_id"],
        "rec_ids": [str(r.dto.rec_id) for r in bread + butter],
    }

    five = recs(s["5"]["product_id"], "TRANSFER")
    assert [(code[r.dto.store.store_id], r.dto.qty) for r in five] == [("C", 30)], "scenario 5"
    out["5"] = {
        "title": s["5"]["title"],
        "product_id": s["5"]["product_id"],
        "rec_ids": [str(r.dto.rec_id) for r in five],
    }
    return out


# --- main ----------------------------------------------------------------------------------------------------------------------


def build_fixtures(dataset_dir: Path) -> dict[str, Any]:
    ds = load_dataset(dataset_dir)
    pl = Planner(ds)
    run_date = pl.run_date
    created = at(pl.end_date, 18, 40)
    b = Builder(ds, pl, _select_products(ds), set(), uid("run", run_date), created)
    b.stale = _stale(ds, pl, run_date)
    lost = _lost_sales(pl, run_date, int(ds.business_rules["kpi_lookback_days"]))

    _balance(b, lost)
    _co_replenish(b)
    _freshness(b)
    pos = _purchase_orders(b)
    inventory = _inventory(b)

    stores = [
        StoreDTO(
            store_id=r.store_id,
            code=str(r.code),
            name=str(r.name),
            region=str(r.region),
            store_type=str(r.store_type),
        ).model_dump(mode="json")
        for r in ds.stores.itertuples()
    ]
    codes = {str(r.code): str(r.store_id) for r in ds.stores.itertuples()}
    users = [
        {
            "username": "admin",
            "user_id": str(uid("user", "admin")),
            "name": "Super Admin",
            "role": "SUPER_ADMIN",
            "store_id": None,
        },
        {
            "username": "sup.a",
            "user_id": str(uid("user", "a")),
            "name": "Asha (Store A)",
            "role": "STORE_SUPERVISOR",
            "store_id": codes["A"],
        },
        {
            "username": "sup.b",
            "user_id": str(uid("user", "b")),
            "name": "Bala (Store B)",
            "role": "STORE_SUPERVISOR",
            "store_id": codes["B"],
        },
        {
            "username": "sup.c",
            "user_id": str(uid("user", "c")),
            "name": "Chitra (Store C)",
            "role": "STORE_SUPERVISOR",
            "store_id": codes["C"],
        },
    ]
    return {
        "generated": {
            "source": "data/synthetic small profile via backend/scripts/export_mock_fixtures.py",
            "seed": ds.manifest["seed"],
            "profile": ds.manifest["profile"],
            "run_date": run_date.isoformat(),
            "note": "Dashboard figures are the last 28 days; the mock returns them for every period.",
        },
        "stores": stores,
        "users": users,
        "latest_run": RunInfoDTO(
            run_id=b.run_id, run_date=run_date, status="SUCCESS", finished_at=at(pl.end_date, 18, 42)
        ).model_dump(mode="json"),
        "inventory": inventory,
        "movements": _movements(b),
        "batches": _batches(b),
        "recommendations": [r.dto.model_dump(mode="json") for r in b.recs],
        "evidence": {str(r.dto.rec_id): EVIDENCE.dump_python(r.evidence, mode="json") for r in b.recs},
        "transfers": [t.model_dump(mode="json") for t in b.transfers],
        "purchase_orders": [po.model_dump(mode="json") for po in pos],
        "dashboard": _dashboard(b, lost, inventory, pos),
        "scenarios": _scenarios(b),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        generate(GeneratorConfig(profile="small"), Path(tmp))
        fixtures = build_fixtures(Path(tmp))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(fixtures, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    counts = {k: len(v) for k, v in fixtures.items() if isinstance(v, list)}
    print(f"Mock fixtures written to {args.out.resolve()} {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
