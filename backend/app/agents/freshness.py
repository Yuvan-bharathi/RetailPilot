"""Freshness Agent (SD-08, spec §1; D-04, D-20, D-28, D-31, D-34, D-47).

For each store-SKU with batches expiring within `expiry_window_days`: FEFO at-risk units per batch (D-31). At-risk
units go first to other HIGH-confidence stores that can sell them before expiry (single receiver first, D-28) as
expiry-aware transfers; what nobody can sell becomes an EXPIRY_ALERT at the holding store. Receivers are evaluated
with the same requirement / availability as stock balancing (PlanningInputs). Evidence is the D-34 union.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.agents.planning_inputs import PlanningInputs
from app.domain.models.enums import Priority, RecStatus, RecType, TransferStatus
from app.domain.models.inventory import Batch
from app.domain.models.observability import DecisionEvidence
from app.domain.models.planning import Recommendation
from app.domain.models.transfers import TransferOrder
from app.domain.repositories.batch_repo import BatchRepo
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.repositories.transfer_repo import TransferRepo
from app.domain.schemas.common import Counterpart
from app.domain.schemas.dtos import BatchRiskRef, ExpiryEvidence, TransferEvidence
from app.tools.freshness import FreshnessTools
from app.tools.numeric import money
from app.tools.transfer_engine import TransferDecisionEngine


class FreshnessAgent(BaseAgent):
    name = "FreshnessAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        batches = BatchRepo(ctx.session).get_expiring(
            store_ids=ctx.store_ids, as_of_date=ctx.run_date, within_days=ctx.params.expiry_window_days
        )
        if not batches:
            ctx.logger.log_tool_call(ctx.run_id, "expiry_scan", {"batches_found": 0}, "no batches", 0, "OK")
            return AgentResult(
                status="SUCCESS", outputs={"batches_scanned": 0, "transfers": 0, "expiry_alerts": 0}
            )

        inputs = PlanningInputs.load(ctx.session, ctx.run_id, ctx.store_ids)
        recs: list[Recommendation] = []
        transfers: list[TransferOrder] = []
        evidence_rows: list[DecisionEvidence] = []

        def add_rec(
            store_id: Any, product_id: Any, rec_type: str, qty: int, evidence: BaseModel, **kw: Any
        ) -> Any:
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
                    status=RecStatus.PENDING.value,
                    priority=kw.get("priority", Priority.HIGH.value),
                    reason=kw.get("reason"),
                    lost_sales_value=kw.get("lost_revenue"),
                )
            )
            evidence_rows.append(
                DecisionEvidence(run_id=ctx.run_id, rec_id=rec_id, data=data, validation_result="VALID")
            )
            return rec_id

        by_store_product: dict[tuple[Any, Any], list[Batch]] = {}
        for b in batches:
            by_store_product.setdefault((b.store_id, b.product_id), []).append(b)

        for (store_id, product_id), held in sorted(
            by_store_product.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))
        ):
            if (store_id, product_id) not in inputs.listings:
                continue
            demand = inputs.demand(store_id, product_id)
            by_id = {b.batch_id: b for b in held}
            for risk in FreshnessTools.at_risk_by_batch(held, demand, ctx.run_date):
                if risk.at_risk <= 0:
                    continue
                ref = BatchRiskRef(
                    batch_no=by_id[risk.batch_id].batch_no,
                    expiry_date=risk.expiry_date,
                    days_left=risk.days_left,
                    batch_qty=risk.qty,
                    at_risk_qty=risk.at_risk,
                )
                receivers = inputs.receiver_states(product_id, exclude=store_id)
                proposals = TransferDecisionEngine.find_expiry_receivers(
                    product_id,
                    risk.at_risk,
                    risk.days_left,
                    store_id,
                    receivers,
                    inputs.routes,
                    inputs.unit_cost(store_id, product_id),
                )
                left = risk.at_risk
                for t in proposals:
                    left -= t.qty
                    receiver = next(s for s in receivers if s.store_id == t.to_store)
                    rec_id = add_rec(
                        t.to_store,
                        product_id,
                        RecType.TRANSFER.value,
                        t.qty,
                        TransferEvidence(
                            kind="TRANSFER",
                            destination_shortage=0,
                            donor=Counterpart(store=inputs.store_ref(store_id), qty=t.qty),
                            donor_surplus=risk.at_risk,
                            donor_protected_requirement=inputs.state(store_id, product_id).requirement,
                            donor_keeps_requirement=True,
                            transfer_qty=t.qty,
                            po_remainder_qty=0,
                            transfer_cost=money(t.transfer_cost),
                            po_incremental_cost=None,
                            expected_delivery=ctx.run_date + timedelta(days=t.transit_days),
                            days_of_cover_before=round(receiver.days_of_cover, 1),
                            days_of_cover_after=round(
                                (receiver.available + t.qty) / max(receiver.daily_demand, 0.01), 1
                            ),
                            expiring_batch=ref,
                        ),
                        reason="EXPIRY_RISK",
                    )
                    transfers.append(
                        TransferOrder(
                            transfer_id=uuid.uuid4(),
                            from_store_id=store_id,
                            to_store_id=t.to_store,
                            product_id=product_id,
                            batch_id=risk.batch_id,
                            qty=t.qty,
                            transfer_cost=money(t.transfer_cost),
                            transit_days=t.transit_days,
                            is_expiry_aware=True,
                            source_rec_id=rec_id,
                            status=TransferStatus.PROPOSED.value,
                            expected_qty=t.qty,
                        )
                    )
                if left > 0:
                    price = inputs.products[product_id].selling_price
                    add_rec(
                        store_id,
                        product_id,
                        RecType.EXPIRY_ALERT.value,
                        left,
                        ExpiryEvidence(
                            kind="EXPIRY",
                            batch=ref.model_copy(update={"at_risk_qty": left}),
                            daily_demand=round(demand, 3),
                            receivers_checked=len(receivers),
                        ),
                        priority=Priority.HIGH.value if ref.days_left <= 3 else Priority.NORMAL.value,
                        reason="EXPIRY_RISK",
                        lost_revenue=money(left * price),
                    )

        PlanningRepo(ctx.session).insert_recommendations(recs)
        ctx.session.add_all(evidence_rows)
        ctx.session.flush()
        TransferRepo(ctx.session).insert_transfers(transfers)
        alerts = sum(1 for r in recs if r.rec_type == RecType.EXPIRY_ALERT.value)
        ctx.logger.log_tool_call(
            ctx.run_id,
            "expiry_scan",
            {"batches_scanned": len(batches)},
            f"{len(transfers)} transfers, {alerts} expiry alerts",
            0,
            "OK",
        )
        return AgentResult(
            status="SUCCESS",
            outputs={"batches_scanned": len(batches), "transfers": len(transfers), "expiry_alerts": alerts},
        )
