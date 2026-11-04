"""Stock Balancing Agent (SD-06, SD-07, spec §8, decisions D-02, D-04, D-05, D-07, D-10, D-14, D-17).

Evaluates store own_requirement and surplus. Compares incremental logistics costs against supplier
order/delivery terms to balance stock between stores before raising purchase orders.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.inventory import InventoryPosition
from app.domain.models.master import (
    Product,
    Store,
    StoreProduct,
    Supplier,
    SupplierProduct,
    SupplierStoreTerms,
)
from app.domain.models.planning import AssociationRule, Recommendation, ReplenishmentNeed
from app.domain.models.transfers import TransferOrder
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.repositories.purchasing_repo import PurchasingRepo
from app.domain.repositories.transfer_repo import TransferRepo
from app.tools.requirement import RequirementCalculator
from app.tools.transfer_engine import TransferDecisionEngine
from app.tools.types import CostInputs, Route, StoreState, StoreSupplyTerms


class StockBalancingAgent(BaseAgent):
    name = "StockBalancingAgent"
    critical = True

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        purchasing_repo = PurchasingRepo(ctx.session)
        transfer_repo = TransferRepo(ctx.session)

        # 1. Fetch forecasts for this run
        forecasts = planning_repo.get_forecasts_by_run(ctx.run_id)

        # 2. Fetch inventory positions
        pos_stmt = select(InventoryPosition).where(InventoryPosition.store_id.in_(ctx.store_ids))
        positions = {(p.store_id, p.product_id): p for p in ctx.session.scalars(pos_stmt).all()}

        # 3. StoreProduct listings and rules
        sp_stmt = select(StoreProduct).where(StoreProduct.store_id.in_(ctx.store_ids))
        store_products = {
            (sp.store_id, sp.product_id): sp for sp in ctx.session.scalars(sp_stmt).all() if sp.is_listed
        }

        # 4. Supplier terms and products
        suppliers = {s.supplier_id: s for s in ctx.session.scalars(select(Supplier)).all()}
        supplier_prods = {
            (sp.supplier_id, sp.product_id): sp for sp in ctx.session.scalars(select(SupplierProduct)).all()
        }
        terms = {
            (t.supplier_id, t.store_id): t for t in ctx.session.scalars(select(SupplierStoreTerms)).all()
        }

        # 5. Routes
        routes_dict = transfer_repo.get_route_matrix()
        tool_routes: dict[tuple[UUID, UUID], Route] = {
            (r.from_store_id, r.to_store_id): Route(
                fixed_cost=r.fixed_cost,
                per_unit_cost=r.per_unit_cost,
                handling_cost_per_unit=r.handling_cost_per_unit,
                transit_days=r.transit_days,
            )
            for r in routes_dict.values()
        }

        # 6. On-order pending from earlier runs (D-14)
        on_order_pending = purchasing_repo.get_on_order_pending(ctx.store_ids)

        # 7. Products and stores
        products = {p.product_id: p for p in ctx.session.scalars(select(Product)).all()}
        stores = {s.store_id: s for s in ctx.session.scalars(select(Store)).all()}

        states_by_product: dict[UUID, list[StoreState]] = {}
        terms_by_product_store: dict[tuple[UUID, UUID], StoreSupplyTerms] = {}

        recs_to_insert: list[Recommendation] = []
        needs_to_insert: list[ReplenishmentNeed] = []
        transfers_to_insert: list[TransferOrder] = []

        # Build store states for each product
        for (store_id, product_id), sp in store_products.items():
            fc = forecasts.get((store_id, product_id))
            daily_demand = fc.daily_demand if fc else 0.0
            confidence = fc.confidence if fc else "HIGH"

            pos = positions.get((store_id, product_id))
            shelf_qty = pos.shelf_qty if pos else 0
            backroom_qty = pos.backroom_qty if pos else 0
            reserved_qty = pos.reserved if pos else 0
            on_order = on_order_pending.get((store_id, product_id), 0)

            # Terms lookup
            supp_id = sp.preferred_supplier_id
            term = terms.get((supp_id, store_id)) if supp_id else None
            supp_prod = supplier_prods.get((supp_id, product_id)) if supp_id else None
            supp = suppliers.get(supp_id) if supp_id else None

            lead_days = RequirementCalculator.lead_time(
                terms_lead=term.lead_time_days if term else None,
                product_lead=supp_prod.lead_time_days if supp_prod else None,
                default_lead=supp.default_lead_time_days if supp else 3,
            )
            delivery_chg = term.delivery_charge if term else Decimal("100.00")
            unit_c = (
                supp_prod.price
                if supp_prod
                else (products[product_id].cost_price if product_id in products else Decimal("10.00"))
            )

            st_terms = StoreSupplyTerms(
                supplier_id=supp_id or uuid.UUID(int=0),
                lead_time_days=lead_days,
                delivery_charge=delivery_chg,
                unit_cost=unit_c,
            )
            terms_by_product_store[(product_id, store_id)] = st_terms

            req = RequirementCalculator.own_requirement(
                daily_demand=daily_demand,
                lead_time_days=lead_days,
                review_period_days=sp.review_period_days,
                safety_stock_days=sp.safety_stock_days,
                min_display_qty=sp.min_display_qty,
            )
            avail = RequirementCalculator.available(
                shelf_qty=shelf_qty,
                backroom_qty=backroom_qty,
                incoming=on_order,
                reserved=reserved_qty,
            )

            if confidence == "LOW":
                if avail < req:
                    recs_to_insert.append(
                        Recommendation(
                            rec_id=uuid.uuid4(),
                            run_id=ctx.run_id,
                            store_id=store_id,
                            product_id=product_id,
                            rec_type="REORDER",
                            qty=req - avail,
                            priority="HIGH",
                            evidence={"requirement": req, "available": avail, "issue": "LOW_CONFIDENCE"},
                            status="NEEDS_REVIEW",
                        )
                    )
                continue

            state = StoreState(
                store_id=store_id,
                requirement=req,
                available=avail,
                daily_demand=daily_demand,
                review_period_days=sp.review_period_days,
            )
            if product_id not in states_by_product:
                states_by_product[product_id] = []
            states_by_product[product_id].append(state)

        # Run two-pass transfer engine
        for product_id, states in states_by_product.items():
            short_stores = [s for s in states if s.surplus < 0]
            if not short_stores:
                continue

            # Route & cost inputs
            prod = products.get(product_id)
            is_perish = (prod.shelf_life_days is not None and prod.shelf_life_days <= 30) if prod else False
            cost_inputs = CostInputs(
                order_fixed_cost=Decimal("200.00"),
                holding_cost_rate_per_day=Decimal("0.001"),
                expiry_risk_pct=Decimal("0.05"),
                is_perishable=is_perish,
                days_to_sell_cap=prod.shelf_life_days if (prod and prod.shelf_life_days) else 90,
                terms_by_store={s.store_id: terms_by_product_store[(product_id, s.store_id)] for s in states},
            )

            plan = TransferDecisionEngine.decide(product_id, states, tool_routes, cost_inputs)

            # Record transfers
            for t in plan.transfers:
                donor_store_name = stores[t.from_store].name if t.from_store in stores else "Store"
                rec_id = uuid.uuid4()
                recs_to_insert.append(
                    Recommendation(
                        rec_id=rec_id,
                        run_id=ctx.run_id,
                        store_id=t.to_store,
                        product_id=product_id,
                        rec_type="TRANSFER",
                        qty=t.qty,
                        priority="NORMAL",
                        evidence={
                            "from_store_name": donor_store_name,
                            "qty": t.qty,
                            "transfer_cost": float(t.transfer_cost),
                        },
                        status="PENDING",
                    )
                )
                transfers_to_insert.append(
                    TransferOrder(
                        transfer_id=uuid.uuid4(),
                        from_store_id=t.from_store,
                        to_store_id=t.to_store,
                        product_id=product_id,
                        qty=t.qty,
                        transfer_cost=t.transfer_cost,
                        transit_days=t.transit_days,
                        source_rec_id=rec_id,
                        status="PROPOSED",
                    )
                )

            # Record PO shortfall needs
            for n in plan.po_needs:
                rec_id = uuid.uuid4()
                recs_to_insert.append(
                    Recommendation(
                        rec_id=rec_id,
                        run_id=ctx.run_id,
                        store_id=n.store_id,
                        product_id=product_id,
                        rec_type="REORDER",
                        qty=n.qty,
                        priority=str(n.priority),
                        evidence={
                            "need_qty": n.qty,
                            "reason": str(n.reason),
                        },
                        status="PENDING",
                    )
                )
                needs_to_insert.append(
                    ReplenishmentNeed(
                        need_id=uuid.uuid4(),
                        run_id=ctx.run_id,
                        store_id=n.store_id,
                        product_id=product_id,
                        qty=n.qty,
                        source="SHORTFALL",
                        reason=str(n.reason),
                        priority=str(n.priority),
                        required_by=ctx.run_date + timedelta(days=3),
                        rec_id=rec_id,
                    )
                )

        # 8. Check Co-Replenishment (D-02)
        rules_stmt = select(AssociationRule).where(AssociationRule.rule_type == "COMPLEMENT")
        comp_rules = ctx.session.scalars(rules_stmt).all()
        reordered_products = {n.product_id for n in needs_to_insert}

        for rule in comp_rules:
            if rule.antecedent_id in reordered_products:
                c_prod = rule.consequent_id
                sp_c = store_products.get((rule.store_id, c_prod))
                if sp_c is not None:
                    fc = forecasts.get((rule.store_id, c_prod))
                    daily_c = fc.daily_demand if fc else 0.0
                    pos_c = positions.get((rule.store_id, c_prod))
                    avail_c = pos_c.available if pos_c else 0
                    req_c = RequirementCalculator.own_requirement(
                        daily_demand=daily_c,
                        lead_time_days=3,
                        review_period_days=sp_c.review_period_days,
                        safety_stock_days=sp_c.safety_stock_days,
                        min_display_qty=sp_c.min_display_qty,
                    )
                    co_qty = RequirementCalculator.co_replenish_qty(
                        available=avail_c,
                        daily_demand=daily_c,
                        review_period_days=sp_c.review_period_days,
                        requirement=req_c,
                    )
                    if co_qty > 0:
                        rec_id = uuid.uuid4()
                        recs_to_insert.append(
                            Recommendation(
                                rec_id=rec_id,
                                run_id=ctx.run_id,
                                store_id=rule.store_id,
                                product_id=c_prod,
                                rec_type="CO_REPLENISH",
                                qty=co_qty,
                                priority="NORMAL",
                                evidence={
                                    "parent_product_id": str(rule.antecedent_id),
                                    "lift": rule.lift,
                                    "qty": co_qty,
                                },
                                status="PENDING",
                            )
                        )
                        needs_to_insert.append(
                            ReplenishmentNeed(
                                need_id=uuid.uuid4(),
                                run_id=ctx.run_id,
                                store_id=rule.store_id,
                                product_id=c_prod,
                                qty=co_qty,
                                source="CO_REPLENISH",
                                reason="CO_REPLENISH",
                                priority="NORMAL",
                                linked_product_id=rule.antecedent_id,
                                lift=rule.lift,
                                required_by=ctx.run_date + timedelta(days=3),
                                rec_id=rec_id,
                            )
                        )

        planning_repo.insert_recommendations(recs_to_insert)
        planning_repo.insert_replenishment_needs(needs_to_insert)
        transfer_repo.insert_transfers(transfers_to_insert)

        return AgentResult(
            status="SUCCESS",
            outputs={
                "transfers": len(transfers_to_insert),
                "reorders": len([r for r in recs_to_insert if r.rec_type == "REORDER"]),
                "co_replenish": len([r for r in recs_to_insert if r.rec_type == "CO_REPLENISH"]),
            },
            step_count=8,
        )
