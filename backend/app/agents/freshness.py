"""Freshness Agent (SD-08, spec §1, decisions D-20, D-28, D-31).

Evaluates FEFO expiry risk per batch, proposes expiry-aware transfers to stores that can sell
at-risk stock before expiration, and raises expiry alerts or markdown recommendations.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.enums import Priority, RecStatus, RecType, TransferStatus
from app.domain.models.inventory import Batch, InventoryPosition
from app.domain.models.master import Product, StoreProduct
from app.domain.models.planning import Recommendation
from app.domain.models.transfers import TransferOrder
from app.domain.repositories.batch_repo import BatchRepo
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.repositories.transfer_repo import TransferRepo
from app.tools.freshness import FreshnessTools
from app.tools.transfer_engine import TransferDecisionEngine
from app.tools.types import Route, StoreState


class FreshnessAgent(BaseAgent):
    name = "FreshnessAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        batch_repo = BatchRepo(ctx.session)
        planning_repo = PlanningRepo(ctx.session)
        transfer_repo = TransferRepo(ctx.session)

        # 1. Batches expiring within window
        window_days = ctx.params.expiry_window_days
        batches = batch_repo.get_expiring(
            store_ids=ctx.store_ids, as_of_date=ctx.run_date, within_days=window_days
        )

        if not batches:
            ctx.logger.log_tool_call(
                ctx.run_id,
                "expiry_scan",
                {"batches_found": 0},
                "no batches expiring within window",
                0,
                "OK",
            )
            return AgentResult(
                status="SUCCESS",
                outputs={"batches_scanned": 0, "transfers": 0, "expiry_alerts": 0},
                step_count=1,
            )

        # 2. Forecasts for this run
        forecasts = planning_repo.get_forecasts_by_run(ctx.run_id)

        # 3. StoreProduct and Inventory positions for receiver capacity
        positions = {
            (p.store_id, p.product_id): p
            for p in ctx.session.scalars(
                select(InventoryPosition).where(InventoryPosition.store_id.in_(ctx.store_ids))
            ).all()
        }
        store_products = {
            (sp.store_id, sp.product_id): sp
            for sp in ctx.session.scalars(
                select(StoreProduct).where(StoreProduct.store_id.in_(ctx.store_ids))
            ).all()
            if sp.is_listed
        }
        products = {p.product_id: p for p in ctx.session.scalars(select(Product)).all()}

        # 4. Route matrix
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

        recs_to_insert: list[Recommendation] = []
        transfers_to_insert: list[TransferOrder] = []
        transfers_count = 0
        expiry_alerts_count = 0

        # Group batches by (store_id, product_id)
        batches_by_store_prod: dict[tuple[UUID, UUID], list[Batch]] = {}
        for b in batches:
            batches_by_store_prod.setdefault((b.store_id, b.product_id), []).append(b)

        for (from_store_id, product_id), sp_batches in batches_by_store_prod.items():
            fc = forecasts.get((from_store_id, product_id))
            daily_demand = fc.daily_demand if fc else 0.0
            prod = products.get(product_id)
            unit_cost = prod.cost_price if prod else Decimal("10.00")

            # Calculate FEFO batch risks
            risks = FreshnessTools.at_risk_by_batch(sp_batches, daily_demand, ctx.run_date)

            # Build states of all stores for this product
            states: list[StoreState] = []
            for s_id in ctx.store_ids:
                s_sp = store_products.get((s_id, product_id))
                if not s_sp:
                    continue
                s_fc = forecasts.get((s_id, product_id))
                s_pos = positions.get((s_id, product_id))
                states.append(
                    StoreState(
                        store_id=s_id,
                        requirement=0,
                        available=s_pos.available if s_pos else 0,
                        daily_demand=s_fc.daily_demand if s_fc else 0.0,
                        review_period_days=s_sp.review_period_days,
                    )
                )

            for risk in risks:
                at_risk = risk.at_risk
                if at_risk <= 0:
                    continue

                # Try to find expiry receivers
                proposals = TransferDecisionEngine.find_expiry_receivers(
                    product_id=product_id,
                    qty=at_risk,
                    days_left=risk.days_left,
                    from_store=from_store_id,
                    states=states,
                    routes=tool_routes,
                    unit_cost=unit_cost,
                )

                for prop in proposals:
                    rec_id = uuid.uuid4()
                    rec = Recommendation(
                        rec_id=rec_id,
                        run_id=ctx.run_id,
                        store_id=prop.to_store,
                        product_id=product_id,
                        rec_type=RecType.TRANSFER.value,
                        qty=prop.qty,
                        priority=Priority.HIGH.value,
                        status=RecStatus.PENDING.value,
                        evidence={
                            "batch_id": str(risk.batch_id),
                            "expiry_date": risk.expiry_date.isoformat(),
                            "days_left": risk.days_left,
                            "at_risk": risk.at_risk,
                            "transfer_cost": str(prop.transfer_cost),
                            "from_store_id": str(from_store_id),
                        },
                    )
                    recs_to_insert.append(rec)

                    transfer = TransferOrder(
                        transfer_id=uuid.uuid4(),
                        from_store_id=from_store_id,
                        to_store_id=prop.to_store,
                        product_id=product_id,
                        batch_id=risk.batch_id,
                        qty=prop.qty,
                        transfer_cost=prop.transfer_cost,
                        transit_days=prop.transit_days,
                        is_expiry_aware=True,
                        source_rec_id=rec_id,
                        status=TransferStatus.PROPOSED.value,
                    )
                    transfers_to_insert.append(transfer)
                    at_risk -= prop.qty
                    transfers_count += 1

                if at_risk > 0:
                    rec_id = uuid.uuid4()
                    rec = Recommendation(
                        rec_id=rec_id,
                        run_id=ctx.run_id,
                        store_id=from_store_id,
                        product_id=product_id,
                        rec_type=RecType.EXPIRY_ALERT.value,
                        qty=at_risk,
                        priority=Priority.HIGH.value,
                        status=RecStatus.PENDING.value,
                        evidence={
                            "batch_id": str(risk.batch_id),
                            "expiry_date": risk.expiry_date.isoformat(),
                            "days_left": risk.days_left,
                            "at_risk": at_risk,
                            "daily_demand": daily_demand,
                        },
                    )
                    recs_to_insert.append(rec)
                    expiry_alerts_count += 1

        planning_repo.insert_recommendations(recs_to_insert)
        transfer_repo.insert_transfers(transfers_to_insert)

        ctx.logger.log_tool_call(
            ctx.run_id,
            "expiry_scan",
            {"batches_scanned": len(batches)},
            f"{transfers_count} transfers, {expiry_alerts_count} expiry alerts",
            0,
            "OK",
        )

        return AgentResult(
            status="SUCCESS",
            outputs={
                "batches_scanned": len(batches),
                "transfers": transfers_count,
                "expiry_alerts": expiry_alerts_count,
            },
            step_count=1,
        )
