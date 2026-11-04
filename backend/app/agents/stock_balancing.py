"""Stock Balancing Agent (SD-06, SD-07, spec §1/§8; D-02, D-04, D-05, D-07, D-10, D-13, D-14, D-17, D-34, D-47).

Per listed store-SKU: own requirement (rule 1, lead time of the supplier serving THAT store) and
available = shelf + backroom + incoming + pending lines of kept POs (D-14) − reserved.
- LOW-confidence store-SKUs are neither donors nor receivers; if short → REORDER with status NEEDS_REVIEW and no
  replenishment need (D-04).
- Pass 1 (D-17) marks the (supplier, store) pairs that need a PO anyway; products are then decided by urgency
  (shortest days of cover first) with the transfer engine: transfers of genuine surplus (donor protected), and PO
  needs for what remains (rules 2–5).
- Co-replenishment (D-02, D-13): complements of a product reordered in the SAME store, from this run's rules with
  lift ≥ co_replenish.min_lift (at most co_replenish.limit per product), only if the complement's supplier already
  delivers to that store this cycle and it would fall below its requirement before the next review.
- Every recommendation carries D-34 evidence (validated DTO), also logged to decision_evidence.
Cost parameters come from the BusinessRule table via RunParams (never code).
"""

from __future__ import annotations

import math
import uuid
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.agents.planning_inputs import PlanningInputs
from app.domain.models.observability import DecisionEvidence
from app.domain.models.planning import AssociationRule, LostSalesEstimate, Recommendation, ReplenishmentNeed
from app.domain.models.transfers import TransferOrder
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.repositories.transfer_repo import TransferRepo
from app.domain.schemas.common import Counterpart, SupplierRef
from app.domain.schemas.dtos import (
    CoReplenishEvidence,
    NeedsReviewEvidence,
    ReorderEvidence,
    TransferEvidence,
)
from app.tools.numeric import money
from app.tools.requirement import RequirementCalculator as RC  # noqa: N817
from app.tools.transfer_engine import TransferDecisionEngine
from app.tools.types import CostInputs, PONeed, StoreState, TransferProposal


class StockBalancingAgent(BaseAgent):
    name = "StockBalancingAgent"
    critical = True

    def run(self, ctx: RunContext) -> AgentResult:
        session, params = ctx.session, ctx.params
        inputs = PlanningInputs.load(session, ctx.run_id, ctx.store_ids)
        planning_repo = PlanningRepo(session)
        forecasts, listings, suppliers, products = (
            inputs.forecasts,
            inputs.listings,
            inputs.suppliers,
            inputs.products,
        )
        routes = inputs.routes
        store_ref, product_ref = inputs.store_ref, inputs.product_ref
        supplier_of, lead_time, state, supply_terms = (
            inputs.supplier_of,
            inputs.lead_time,
            inputs.state,
            inputs.supply_terms,
        )
        lost = {
            (r.store_id, r.product_id): r
            for r in session.scalars(select(LostSalesEstimate).where(LostSalesEstimate.run_id == ctx.run_id))
        }

        recs: list[Recommendation] = []
        needs: list[ReplenishmentNeed] = []
        transfers: list[TransferOrder] = []
        evidence_rows: list[DecisionEvidence] = []

        def add_rec(
            store_id: UUID, product_id: UUID, rec_type: str, qty: int, evidence: BaseModel, **kw: Any
        ) -> UUID:
            rec_id = uuid.uuid4()
            data = evidence.model_dump(mode="json")
            recs.append(
                Recommendation(
                    rec_id=rec_id,
                    run_id=ctx.run_id,
                    store_id=store_id,
                    product_id=product_id,
                    rec_type=rec_type,
                    qty=qty,
                    evidence=data,
                    priority=kw.get("priority", "NORMAL"),
                    status=kw.get("status", "PENDING"),
                    reason=kw.get("reason"),
                    lost_sales_value=kw.get("lost_revenue"),
                    lost_profit=kw.get("lost_profit"),
                )
            )
            evidence_rows.append(
                DecisionEvidence(run_id=ctx.run_id, rec_id=rec_id, data=data, validation_result="VALID")
            )
            return rec_id

        # --- states; LOW confidence → NEEDS_REVIEW (D-04) ------------------------------------------------------
        states_by_product: dict[UUID, list[StoreState]] = {}
        for (store_id, product_id), _sp in sorted(
            listings.items(), key=lambda kv: (str(kv[0][1]), str(kv[0][0]))
        ):
            st = state(store_id, product_id)
            fc = forecasts.get((store_id, product_id))
            if fc is not None and fc.confidence == "LOW":
                if st.available < st.requirement:
                    qty = st.requirement - st.available
                    add_rec(
                        store_id,
                        product_id,
                        "REORDER",
                        qty,
                        NeedsReviewEvidence(
                            kind="NEEDS_REVIEW",
                            reason="LOW_CONFIDENCE",
                            own_requirement=st.requirement,
                            available=st.available,
                            suggested_qty=qty,
                            detail=f"No sales for more than {params.stale_days} days while stock is held, "
                            "or too little in-stock history.",
                        ),
                        status="NEEDS_REVIEW",
                        reason="LOW_CONFIDENCE",
                    )
                continue
            if supply_terms(store_id, product_id) is None:
                continue  # no serving supplier: handled by the PO agent as NO_ELIGIBLE_SUPPLIER if it is ever short
            states_by_product.setdefault(product_id, []).append(st)

        # --- pass 1 (D-17) and decisions by urgency -------------------------------------------------------------
        all_terms = {
            (s.store_id, p): term
            for p, sts in states_by_product.items()
            for s in sts
            if (term := supply_terms(s.store_id, p)) is not None
        }
        planned = set(TransferDecisionEngine.mark_po_pairs(states_by_product, all_terms))

        def cost_inputs(product_id: UUID) -> CostInputs:
            life = products[product_id].shelf_life_days
            return CostInputs(
                terms_by_store={
                    s.store_id: all_terms[(s.store_id, product_id)] for s in states_by_product[product_id]
                },
                order_fixed_cost=params.order_fixed_cost,
                holding_cost_rate_per_day=params.holding_cost_rate_per_day,
                expiry_risk_pct=params.expiry_risk_pct,
                is_perishable=life is not None and life <= params.perishable_max_shelf_life_days,
                days_to_sell_cap=life if life is not None else params.days_to_sell_default_cap,
                planned_supplier_stores=frozenset(planned),
            )

        def urgency(product_id: UUID) -> tuple[float, str]:
            short = [s.days_of_cover for s in states_by_product[product_id] if s.available < s.requirement]
            return (min(short) if short else math.inf, str(product_id))

        shortfalls: list[tuple[PONeed, UUID]] = []
        for product_id in sorted(states_by_product, key=urgency):
            sts = states_by_product[product_id]
            if not any(s.available < s.requirement for s in sts):
                continue
            plan = TransferDecisionEngine.decide(product_id, sts, routes, cost_inputs(product_id))
            by_store = {s.store_id: s for s in sts}
            remainder = {n.store_id: n.qty for n in plan.po_needs}
            for t in plan.transfers:
                self._transfer(ctx, t, by_store[t.to_store], remainder.get(t.to_store, 0), lead_time, store_ref,
                               add_rec, transfers)  # fmt: skip
            for n in plan.po_needs:
                st = by_store[n.store_id]
                sp = listings[(n.store_id, product_id)]
                ls = lost.get((n.store_id, product_id))
                lost_rev = ls.lost_revenue if ls is not None and ls.lost_revenue > 0 else None
                lost_prof = ls.lost_profit if ls is not None and ls.lost_profit > 0 else None
                rec_id = add_rec(
                    n.store_id,
                    product_id,
                    "REORDER",
                    n.qty,
                    ReorderEvidence(
                        kind="REORDER",
                        reason=cast(Any, n.reason),
                        daily_demand=round(st.daily_demand, 3),
                        lead_time_days=lead_time(n.store_id, product_id),
                        review_period_days=sp.review_period_days,
                        safety_stock_days=sp.safety_stock_days,
                        min_display_qty=sp.min_display_qty,
                        own_requirement=st.requirement,
                        available=st.available,
                        need_qty=st.requirement - st.available,
                        transferred_qty=int(str(n.evidence.get("transferred_qty", 0))),
                        days_of_cover=round(st.days_of_cover, 1),
                        supplier=SupplierRef(supplier_id=n.supplier_id, name=suppliers[n.supplier_id].name),
                        lost_revenue=lost_rev,
                        lost_profit=lost_prof,
                    ),
                    priority=n.priority,
                    reason=n.reason,
                    lost_revenue=lost_rev,
                    lost_profit=lost_prof,
                )
                shortfalls.append((n, rec_id))
                planned.add((n.supplier_id, n.store_id))

        for n, rec_id in shortfalls:
            needs.append(self._need(ctx, n, "SHORTFALL", rec_id, lead_time(n.store_id, n.product_id)))

        # --- co-replenishment (D-02, D-13) ---------------------------------------------------------------------
        delivering = {(n.supplier_id, n.store_id) for n, _ in shortfalls}
        existing = {(n.store_id, n.product_id) for n, _ in shortfalls} | {
            (r.store_id, r.product_id) for r in recs if r.status == "NEEDS_REVIEW"
        }
        rules = list(
            session.scalars(
                select(AssociationRule)
                .where(
                    AssociationRule.run_id == ctx.run_id,
                    AssociationRule.rule_type == "COMPLEMENT",
                    AssociationRule.lift >= float(params.co_replenish["min_lift"]),
                )
                .order_by(AssociationRule.lift.desc(), AssociationRule.consequent_id)
            )
        )
        by_antecedent: dict[tuple[UUID, UUID], list[AssociationRule]] = {}
        for rule in rules:
            by_antecedent.setdefault((rule.store_id, rule.antecedent_id), []).append(rule)
        limit = int(params.co_replenish["limit"])
        for n, _ in list(shortfalls):
            for rule in by_antecedent.get((n.store_id, n.product_id), [])[:limit]:
                key = (n.store_id, rule.consequent_id)
                if key in existing or key not in listings:
                    continue
                fc = forecasts.get(key)
                if fc is None or fc.confidence == "LOW":
                    continue
                st = state(*key)
                qty = RC.co_replenish_qty(
                    st.available, st.daily_demand, st.review_period_days, st.requirement
                )
                supplier = supplier_of(*key)
                if qty <= 0 or supplier is None or (supplier, n.store_id) not in delivering:
                    continue
                rec_id = add_rec(
                    n.store_id,
                    rule.consequent_id,
                    "CO_REPLENISH",
                    qty,
                    CoReplenishEvidence(
                        kind="CO_REPLENISH",
                        linked_product=product_ref(n.product_id),
                        support=round(rule.support, 4),
                        confidence=round(rule.confidence, 3),
                        lift=round(rule.lift, 2),
                        daily_demand=round(st.daily_demand, 3),
                        review_period_days=st.review_period_days,
                        own_requirement=st.requirement,
                        available=st.available,
                        projected_at_next_review=round(
                            st.available - st.daily_demand * st.review_period_days, 2
                        ),
                        supplier=SupplierRef(supplier_id=supplier, name=suppliers[supplier].name),
                    ),
                    reason="CO_REPLENISH",
                )
                co_need = PONeed(n.store_id, rule.consequent_id, qty, "NORMAL", "CO_REPLENISH", supplier)
                need = self._need(ctx, co_need, "CO_REPLENISH", rec_id, lead_time(*key))
                need.linked_product_id, need.lift = n.product_id, rule.lift
                needs.append(need)
                existing.add(key)

        planning_repo.insert_recommendations(recs)
        session.add_all(evidence_rows)
        session.flush()
        planning_repo.insert_replenishment_needs(needs)
        TransferRepo(session).insert_transfers(transfers)

        return AgentResult(
            status="SUCCESS",
            outputs={
                "transfers": len(transfers),
                "reorders": sum(1 for r in recs if r.rec_type == "REORDER" and r.status == "PENDING"),
                "needs_review": sum(1 for r in recs if r.status == "NEEDS_REVIEW"),
                "co_replenish": sum(1 for r in recs if r.rec_type == "CO_REPLENISH"),
            },
            step_count=1,
        )

    @staticmethod
    def _need(ctx: RunContext, n: PONeed, source: str, rec_id: UUID, lead: int) -> ReplenishmentNeed:
        return ReplenishmentNeed(
            need_id=uuid.uuid4(),
            run_id=ctx.run_id,
            store_id=n.store_id,
            product_id=n.product_id,
            qty=n.qty,
            source=source,
            reason=n.reason,
            priority=n.priority,
            rec_id=rec_id,
            required_by=ctx.run_date + timedelta(days=lead),
        )

    @staticmethod
    def _transfer(
        ctx: RunContext,
        t: TransferProposal,
        short: StoreState,
        po_remainder: int,
        lead_time: Any,
        store_ref: Any,
        add_rec: Any,
        transfers: list[TransferOrder],
    ) -> None:
        demand = max(short.daily_demand, 0.01)
        evidence = TransferEvidence(
            kind="TRANSFER",
            destination_shortage=int(str(t.evidence["need"])),
            donor=Counterpart(store=store_ref(t.from_store), qty=t.qty),
            donor_surplus=int(str(t.evidence["donor_surplus"])),
            donor_protected_requirement=int(str(t.evidence["donor_requirement"])),
            donor_keeps_requirement=True,
            transfer_qty=t.qty,
            po_remainder_qty=po_remainder,
            transfer_cost=money(t.transfer_cost),
            po_incremental_cost=money(t.po_cost_avoided),
            expected_delivery=ctx.run_date + timedelta(days=t.transit_days),
            days_of_cover_before=round(short.available / demand, 1),
            days_of_cover_after=round((short.available + t.qty) / demand, 1),
        )
        rec_id = add_rec(
            t.to_store,
            t.product_id,
            "TRANSFER",
            t.qty,
            evidence,
            priority=TransferDecisionEngine._priority(short, lead_time(t.to_store, t.product_id)),
            reason="SURPLUS_TRANSFER" if not po_remainder else "PARTIAL_SURPLUS",
        )
        transfers.append(
            TransferOrder(
                transfer_id=uuid.uuid4(),
                from_store_id=t.from_store,
                to_store_id=t.to_store,
                product_id=t.product_id,
                qty=t.qty,
                transfer_cost=money(t.transfer_cost),
                transit_days=t.transit_days,
                is_expiry_aware=False,
                source_rec_id=rec_id,
                status="PROPOSED",
                expected_qty=t.qty,
            )
        )
