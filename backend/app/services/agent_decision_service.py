"""Decision log (docs/09 §3.7, D-50): every recommendation / transfer / PO-need / PO an agent creates writes one
`agent_decision` row; the human outcome is updated by the recommendation, transfer and approval workflows.

Attribution: the orchestrator calls `record_stage_decisions` right after each stage, so a recommendation of this
run without a decision yet belongs to the stage that just finished (stages run in a fixed order).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domain.models.agents import AgentDecision, AgentDraft
from app.domain.models.enums import DecisionOutcome, DraftStatus, RecStatus
from app.domain.models.master import Product, Store
from app.domain.models.planning import Recommendation
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.transfers import TransferOrder

#: (agent_key, rec_type, rec status) → decision type; status "*" = any
_REC_DECISIONS: dict[str, dict[str, str]] = {
    "stock_balancing": {
        "TRANSFER": "TRANSFER_CHOSEN_OVER_PO",
        "REORDER": "PO_NEED_CREATED",
        "CO_REPLENISH": "CO_REPLENISH_LINKED",
    },
    "freshness": {
        "TRANSFER": "EXPIRY_TRANSFER",
        "EXPIRY_ALERT": "EXPIRY_ALERT_RAISED",
        "MARKDOWN": "EXPIRY_ALERT_RAISED",
    },
    "related_product": {"ASSORTMENT_GAP": "ASSORTMENT_GAP_FOUND"},
}

_LABEL = {
    "TRANSFER_CHOSEN_OVER_PO": "Transfer",
    "PO_NEED_CREATED": "Order from supplier",
    "CO_REPLENISH_LINKED": "Co-replenish",
    "EXPIRY_TRANSFER": "Expiry transfer",
    "EXPIRY_ALERT_RAISED": "Expiry alert",
    "ASSORTMENT_GAP_FOUND": "Assortment gap",
    "NEEDS_REVIEW_RAISED": "Needs review",
}


def record_stage_decisions(session: Session, run_id: UUID, agent_key: str, mode: str = "LIVE") -> int:
    """Write decisions for the outputs of `agent_key` in run `run_id` that have no decision yet."""
    if agent_key == "purchase_order":
        return _record_po_decisions(session, run_id, mode)
    mapping = _REC_DECISIONS.get(agent_key)
    if not mapping:
        return 0
    decided = select(AgentDecision.rec_id).where(
        AgentDecision.run_id == run_id, AgentDecision.rec_id.is_not(None)
    )
    rows = session.execute(
        select(Recommendation, Store.name, Product.name)
        .join(Store, Store.store_id == Recommendation.store_id)
        .join(Product, Product.product_id == Recommendation.product_id)
        .where(
            Recommendation.run_id == run_id,
            Recommendation.rec_type.in_(list(mapping)),
            Recommendation.rec_id.not_in(decided),
        )
    ).all()
    if not rows:
        return 0
    transfers = dict(
        session.execute(
            select(TransferOrder.source_rec_id, TransferOrder.transfer_id).where(
                TransferOrder.source_rec_id.in_([r[0].rec_id for r in rows])
            )
        ).all()
    )
    out: list[dict[str, Any]] = []
    for rec, store_name, product_name in rows:
        dtype = "NEEDS_REVIEW_RAISED" if rec.status == RecStatus.NEEDS_REVIEW.value else mapping[rec.rec_type]
        out.append(
            {
                "decision_id": uuid.uuid4(),
                "run_id": run_id,
                "agent_key": agent_key,
                "decision_type": dtype,
                "mode": mode,
                "store_id": rec.store_id,
                "product_id": rec.product_id,
                "rec_id": rec.rec_id,
                "transfer_id": transfers.get(rec.rec_id),
                "summary": f"{_LABEL[dtype]}: {rec.qty} × {product_name} for {store_name}",
                "evidence_ref": {
                    "rec_id": str(rec.rec_id),
                    "evidence_kind": (rec.evidence or {}).get("kind"),
                },
                "outcome": DecisionOutcome.PENDING.value,
            }
        )
    session.execute(insert(AgentDecision), out)
    return len(out)


def _record_po_decisions(session: Session, run_id: UUID, mode: str) -> int:
    decided = select(AgentDecision.po_id).where(
        AgentDecision.run_id == run_id, AgentDecision.po_id.is_not(None)
    )
    pos = session.scalars(
        select(PurchaseOrder).where(PurchaseOrder.run_id == run_id, PurchaseOrder.po_id.not_in(decided))
    ).all()
    out: list[dict[str, Any]] = []
    for po in pos:
        lines = session.execute(select(POLine.store_id, POLine.qty).where(POLine.po_id == po.po_id)).all()
        stores = {s for s, _ in lines}
        out.append(
            {
                "decision_id": uuid.uuid4(),
                "run_id": run_id,
                "agent_key": "purchase_order",
                "decision_type": "PO_DRAFTED",
                "mode": mode,
                "store_id": next(iter(stores)) if len(stores) == 1 else None,
                "po_id": po.po_id,
                "summary": f"Consolidated PO with {len(lines)} lines for {len(stores)} store(s), "
                f"{sum(q for _, q in lines)} units — {po.status}",
                "evidence_ref": {"po_id": str(po.po_id)},
                "outcome": DecisionOutcome.PENDING.value,
            }
        )
    if out:
        session.execute(insert(AgentDecision), out)
    return len(out)


def record_decision(
    session: Session,
    *,
    run_id: UUID,
    agent_key: str,
    decision_type: str,
    summary: str,
    mode: str = "LIVE",
    outcome: str = DecisionOutcome.NOT_APPLICABLE.value,
    store_id: UUID | None = None,
    product_id: UUID | None = None,
    rec_id: UUID | None = None,
    draft_id: UUID | None = None,
    evidence_ref: dict[str, Any] | None = None,
) -> UUID:
    """A decision of an Objective III agent (answer, flag, coordinator action, draft)."""
    decision = AgentDecision(
        decision_id=uuid.uuid4(),
        run_id=run_id,
        agent_key=agent_key,
        decision_type=decision_type,
        mode=mode,
        store_id=store_id,
        product_id=product_id,
        rec_id=rec_id,
        draft_id=draft_id,
        summary=summary[:500],
        evidence_ref=evidence_ref or {},
        outcome=outcome,
    )
    session.add(decision)
    session.flush()
    return decision.decision_id


def mark_superseded(session: Session) -> int:
    """PENDING decisions whose recommendation / PO was superseded by a later run."""
    n1 = session.execute(
        update(AgentDecision)
        .where(
            AgentDecision.outcome == DecisionOutcome.PENDING.value,
            AgentDecision.rec_id.in_(
                select(Recommendation.rec_id).where(Recommendation.status == "SUPERSEDED")
            ),
        )
        .values(outcome=DecisionOutcome.SUPERSEDED.value, outcome_at=datetime.now(UTC))
    )
    n2 = session.execute(
        update(AgentDecision)
        .where(
            AgentDecision.outcome == DecisionOutcome.PENDING.value,
            AgentDecision.po_id.in_(select(PurchaseOrder.po_id).where(PurchaseOrder.status == "SUPERSEDED")),
        )
        .values(outcome=DecisionOutcome.SUPERSEDED.value, outcome_at=datetime.now(UTC))
    )
    session.execute(
        update(AgentDraft)
        .where(
            AgentDraft.status == DraftStatus.DRAFT.value,
            AgentDraft.source_rec_id.in_(
                select(Recommendation.rec_id).where(Recommendation.status == "SUPERSEDED")
            ),
        )
        .values(status=DraftStatus.SUPERSEDED.value)
    )
    return int(getattr(n1, "rowcount", 0) or 0) + int(getattr(n2, "rowcount", 0) or 0)


_OUTCOME_OF_ACTION = {
    "ACCEPT": "ACCEPTED",
    "ACCEPTED": "ACCEPTED",
    "APPROVED": "ACCEPTED",
    "EDIT": "EDITED",
    "EDITED": "EDITED",
    "REJECT": "REJECTED",
    "REJECTED": "REJECTED",
}


async def update_outcome(
    session: AsyncSession,
    *,
    action: str,
    user_id: UUID | None,
    reason: str | None = None,
    rec_ids: Sequence[UUID] | None = None,
    transfer_ids: Iterable[UUID] | None = None,
    po_id: UUID | None = None,
) -> None:
    """Human outcome from the existing workflows (recommendation action, transfer accept/reject, PO approval).
    Only PENDING decisions change: the first human decision is the outcome. Does not commit."""
    outcome = _OUTCOME_OF_ACTION.get(action)
    if outcome is None:
        return
    now = datetime.now(UTC)
    values = {"outcome": outcome, "outcome_reason": reason, "outcome_by": user_id, "outcome_at": now}
    conds: list[ColumnElement[bool]] = []
    if rec_ids:
        conds.append(AgentDecision.rec_id.in_(list(rec_ids)))
    tids = list(transfer_ids or [])
    if tids:
        conds.append(AgentDecision.transfer_id.in_(tids))
    if po_id is not None:
        conds.append(AgentDecision.po_id == po_id)
    for cond in conds:
        await session.execute(
            update(AgentDecision)
            .where(cond, AgentDecision.outcome == DecisionOutcome.PENDING.value, AgentDecision.mode == "LIVE")
            .values(**values)
        )
    if rec_ids:
        draft_status = DraftStatus.REJECTED.value if outcome == "REJECTED" else DraftStatus.ACCEPTED.value
        await session.execute(
            update(AgentDraft)
            .where(AgentDraft.source_rec_id.in_(list(rec_ids)), AgentDraft.status == DraftStatus.DRAFT.value)
            .values(status=draft_status)
        )
