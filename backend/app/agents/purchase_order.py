"""Purchase Order Agent (SD-09, spec §2, decisions D-01, D-07, D-08, D-16, D-22, D-29).

Selects eligible suppliers, consolidates needs into draft POs, applies pack/MOQ rounding and
budget trimming, determines L1/L2 approval levels, and generates natural-language explanations.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.core.config import get_settings
from app.domain.models.enums import ApprovalLevelRequired, LineStatus, POStatus, Priority, RecStatus
from app.domain.models.master import StoreProduct, Supplier, SupplierStoreTerms
from app.domain.models.observability import DecisionEvidence
from app.domain.models.planning import Recommendation
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.repositories.purchasing_repo import PurchasingRepo
from app.domain.schemas.dtos import NeedsReviewEvidence
from app.services.explanation_service import ExplanationInput, ExplanationService
from app.tools.po_builder import POBuilder
from app.tools.requirement import RequirementCalculator
from app.tools.types import ReplenishmentNeed as ToolNeed
from app.tools.types import SupplierOffer


class PurchaseOrderAgent(BaseAgent):
    name = "PurchaseOrderAgent"
    critical = True

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        purchasing_repo = PurchasingRepo(ctx.session)

        # 1. Get replenishment needs for this run
        needs = planning_repo.get_needs_by_run(ctx.run_id)
        if not needs:
            return AgentResult(
                status="SUCCESS",
                outputs={"pos": 0, "needs_review": 0, "budget_trimmed": 0},
                step_count=1,
            )

        # 2. StoreProduct for preferred supplier & ABC class
        sp_stmt = select(StoreProduct).where(StoreProduct.store_id.in_(ctx.store_ids))
        store_products = {(sp.store_id, sp.product_id): sp for sp in ctx.session.scalars(sp_stmt).all()}

        # 3. Supplier offers for needed products
        product_ids = list({n.product_id for n in needs})
        offers_by_prod = purchasing_repo.get_offers(product_ids)
        store_leads = {
            (t.supplier_id, t.store_id): t.lead_time_days
            for t in ctx.session.scalars(select(SupplierStoreTerms))
        }
        default_leads = {
            s.supplier_id: s.default_lead_time_days for s in ctx.session.scalars(select(Supplier))
        }

        # 4. Business rules and remaining budget
        rules = purchasing_repo.get_business_rules()
        week_start = ctx.run_date - timedelta(days=ctx.run_date.weekday())
        committed_spend = purchasing_repo.get_committed_spend(week_start)
        budget_remaining = max(Decimal("0.00"), rules.weekly_budget - committed_spend)

        assigned: list[tuple[ToolNeed, SupplierOffer]] = []
        recs_to_insert: list[Recommendation] = []
        needs_review_count = 0
        budget_trimmed_count = 0

        # 5. Match needs to eligible suppliers
        for need in needs:
            sp = store_products.get((need.store_id, need.product_id))
            preferred_sup = sp.preferred_supplier_id if sp else None
            abc_class = sp.abc_class if sp else None

            tool_need = ToolNeed(
                store_id=need.store_id,
                product_id=need.product_id,
                qty=need.qty,
                run_date=ctx.run_date,
                required_by=need.required_by,
                priority="HIGH" if need.priority == Priority.HIGH.value else "NORMAL",
                reason=need.reason,  # type: ignore[arg-type]
                preferred_supplier_id=preferred_sup,
                abc_class=abc_class,
                source_rec_id=need.rec_id,
                need_id=need.need_id,
            )

            # Rule 1 / D-05: a supplier's lead time for THIS store (store terms → offer → supplier default), the
            # same lead time the requirement and required_by were computed with.
            prod_offers = [
                replace(
                    o,
                    lead_time_days=RequirementCalculator.lead_time(
                        store_leads.get((o.supplier_id, need.store_id)),
                        o.lead_time_days,
                        default_leads.get(o.supplier_id, o.lead_time_days),
                    ),
                )
                for o in offers_by_prod.get(need.product_id, [])
            ]
            selected_offer = POBuilder.select_supplier(
                need=tool_need,
                offers=prod_offers,
                required_by=need.required_by,
            )

            if selected_offer is None:
                # D-07: the shortfall's recommendation goes to manual review (no second recommendation)
                if need.rec_id is not None:
                    _to_review(ctx, need.rec_id, "NO_ELIGIBLE_SUPPLIER",
                               f"No active supplier can deliver by {need.required_by.isoformat()}.")  # fmt: skip
                needs_review_count += 1
            else:
                assigned.append((tool_need, selected_offer))

        # 6. Consolidate into Draft POs
        draft_pos = POBuilder.consolidate(assigned)

        pos_to_insert: list[PurchaseOrder] = []
        now_dt = datetime.now(UTC)
        deadline_dt = now_dt + timedelta(hours=rules.l1_deadline_hours)

        for draft_po in draft_pos:
            # Round lines to pack / MOQ
            rounded_lines = [
                replace(
                    line,
                    qty=POBuilder.round_to_pack(line.qty, line.order_pack_size, line.moq),
                )
                for line in draft_po.lines
            ]
            po = replace(draft_po, lines=tuple(rounded_lines))

            # Validate against budget and MOQ
            val_res = POBuilder.validate(po, rules, budget_remaining)
            flags = list(po.flags)
            status = POStatus.PENDING_L1.value

            if val_res.budget_exceeded:
                trim_res = POBuilder.prioritise_within_budget(po, budget_remaining)
                for skipped in trim_res.skipped:
                    # D-29: a line the budget cannot fit goes to manual review on its own recommendation
                    if skipped.source_rec_id is not None:
                        _to_review(ctx, skipped.source_rec_id, "BUDGET",
                                   "Does not fit the remaining weekly budget after reducing other lines.")  # fmt: skip
                    budget_trimmed_count += 1
                po = trim_res.po
                flags.append("BUDGET_TRIMMED")
                budget_remaining = max(Decimal("0.00"), budget_remaining - po.total_value)
            elif not val_res.ok:
                flags.extend(val_res.errors)
                status = POStatus.DRAFT.value
            else:
                budget_remaining = max(Decimal("0.00"), budget_remaining - po.total_value)

            if not po.active_lines:
                continue

            required_level = (
                ApprovalLevelRequired.L2.value
                if po.total_value >= rules.po_l2_threshold
                else ApprovalLevelRequired.L1.value
            )

            po_id = uuid.uuid4()
            po_record = PurchaseOrder(
                po_id=po_id,
                supplier_id=po.supplier_id,
                run_id=ctx.run_id,
                total_value=po.total_value,
                required_level=required_level,
                status=status,
                flags=flags,
                l1_deadline=deadline_dt,
            )

            po_lines: list[POLine] = []
            for line in po.active_lines:
                po_lines.append(
                    POLine(
                        po_line_id=uuid.uuid4(),
                        po_id=po_id,
                        store_id=line.store_id,
                        product_id=line.product_id,
                        qty=line.qty,
                        unit_price=line.unit_price,
                        source_rec_id=line.source_rec_id or uuid.uuid4(),
                        line_status=LineStatus.PENDING.value,
                    )
                )

            po_record.lines = po_lines
            pos_to_insert.append(po_record)

        if recs_to_insert:
            planning_repo.insert_recommendations(recs_to_insert)
        if pos_to_insert:
            purchasing_repo.insert_purchase_orders(pos_to_insert)

        # 7. Natural-language explanations via ExplanationService
        # global "All LLM agents" switch off (D-50) → explanations use the deterministic templates
        llm_off = ctx.extra.get("llm_enabled") is False
        explanation_service = ExplanationService(
            ctx.session,
            settings=get_settings().model_copy(update={"llm_provider": "template"}) if llm_off else None,
        )
        items_to_explain: list[tuple[str, UUID, ExplanationInput]] = []

        all_recs = planning_repo.get_recs_by_run(ctx.run_id)
        for r in all_recs:
            evidence_dict = dict(r.evidence or {})
            evidence_dict.setdefault("qty", r.qty)
            items_to_explain.append(
                (
                    "rec",
                    r.rec_id,
                    ExplanationInput(
                        kind=r.rec_type,
                        evidence=evidence_dict,
                    ),
                )
            )

        for p in pos_to_insert:
            items_to_explain.append(
                (
                    "po",
                    p.po_id,
                    ExplanationInput(
                        kind="PURCHASE_ORDER",
                        evidence={
                            "total_value": str(p.total_value),
                            "line_count": len(p.lines),
                            "required_level": p.required_level,
                            "flags": p.flags,
                        },
                    ),
                )
            )

        # Explain in batches of 20
        batch_size = 20
        for i in range(0, len(items_to_explain), batch_size):
            chunk = items_to_explain[i : i + batch_size]
            explanations = explanation_service.explain([c[2] for c in chunk], run_id=ctx.run_id)
            for (target_kind, target_id, _), expl in zip(chunk, explanations, strict=False):
                if target_kind == "rec":
                    planning_repo.set_explanation(target_id, expl)
                else:
                    purchasing_repo.set_explanation(target_id, expl)

        ctx.logger.log_tool_call(
            ctx.run_id,
            "po_generation",
            {"draft_pos": len(draft_pos)},
            f"{len(pos_to_insert)} POs created, {needs_review_count} needs review, {budget_trimmed_count} budget trimmed",
            0,
            "OK",
        )

        return AgentResult(
            status="SUCCESS",
            outputs={
                "pos": len(pos_to_insert),
                "needs_review": needs_review_count,
                "budget_trimmed": budget_trimmed_count,
            },
            step_count=1,
        )


def _to_review(ctx: RunContext, rec_id: UUID, reason: str, detail: str) -> None:
    """Move a recommendation to NEEDS_REVIEW with D-34 NeedsReviewEvidence built from its own figures."""
    rec = ctx.session.get(Recommendation, rec_id)
    if rec is None:
        return
    previous = dict(rec.evidence or {})
    evidence = NeedsReviewEvidence(
        kind="NEEDS_REVIEW",
        reason=cast(Any, reason),
        own_requirement=int(previous.get("own_requirement", 0)),
        available=int(previous.get("available", 0)),
        suggested_qty=rec.qty,
        detail=detail,
    ).model_dump(mode="json")
    rec.status, rec.reason, rec.evidence = RecStatus.NEEDS_REVIEW.value, reason, evidence
    ctx.session.execute(
        update(DecisionEvidence).where(DecisionEvidence.rec_id == rec_id).values(data=evidence)
    )
