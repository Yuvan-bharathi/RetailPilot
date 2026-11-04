"""Approval service: line-level decisions, deadline enforcement, and PO splitting (SD-10, SD-14)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from app.domain.models.enums import (
    ApprovalLevel,
    ApprovalLevelRequired,
    LineStatus,
    POStatus,
    RecStatus,
    Role,
)
from app.domain.models.planning import Recommendation
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.transfers import Approval, BusinessRule
from app.domain.models.users import AppUser
from app.domain.repositories.purchasing_repo import PurchasingRepo
from app.services.cache_service import CacheService
from app.tools.po_builder import POBuilder
from app.tools.types import DraftPO, DraftPOLine

logger = logging.getLogger(__name__)


class POLineEdit(BaseModel):
    po_line_id: UUID
    qty: int = Field(ge=0)


class ApprovalRequest(BaseModel):
    entity_type: Literal["PO", "TRANSFER"] = "PO"
    entity_id: UUID
    store_id: UUID | None = None
    decision: Literal["APPROVED", "EDITED", "REJECTED"]
    line_edits: list[POLineEdit] = Field(default_factory=list)
    reason: str | None = None


class ApprovalResult(BaseModel):
    po_id: UUID
    status: str
    child_po_id: UUID | None = None
    approval_id: UUID


class ApprovalService:
    def __init__(self, session: Session | None = None, cache_service: CacheService | None = None) -> None:
        self.session = session
        self.cache_service = cache_service or CacheService()
        if session is not None:
            self.purchasing_repo = PurchasingRepo(session)

    def expire_overdue(self, now: datetime | None = None) -> int:
        """Enforces approval deadlines for overdue PENDING_L1 POs (SD-14)."""
        if self.session is None:
            raise RuntimeError("Sync session required for expire_overdue")
        if now is None:
            now = datetime.now(UTC)

        rules = self.purchasing_repo.get_business_rules()
        action = rules.deadline_action

        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(
                PurchaseOrder.status == POStatus.PENDING_L1.value,
                PurchaseOrder.l1_deadline <= now,
            )
            .with_for_update(skip_locked=True)
        )
        overdue_pos = list(self.session.scalars(stmt).all())
        processed_count = 0

        for po in overdue_pos:
            pending_lines = [line for line in po.lines if line.line_status == LineStatus.PENDING.value]
            if not pending_lines:
                continue

            if action == "ESCALATE":
                line_ids = [line.po_line_id for line in pending_lines]
                self.session.execute(
                    update(POLine)
                    .where(POLine.po_line_id.in_(line_ids))
                    .values(line_status="ESCALATED")
                )
                logger.info("Escalated %d lines on PO %s to Super Admin", len(line_ids), po.po_id)
            else:  # EXPIRE
                line_ids = [line.po_line_id for line in pending_lines]
                self.session.execute(
                    update(POLine)
                    .where(POLine.po_line_id.in_(line_ids))
                    .values(line_status=LineStatus.EXPIRED.value)
                )

                approved_lines = [
                    line
                    for line in po.lines
                    if line.line_status in (LineStatus.APPROVED.value, LineStatus.EDITED.value)
                ]

                if not approved_lines:
                    po.status = POStatus.REJECTED.value
                else:
                    draft_lines = [
                        DraftPOLine(
                            store_id=line.store_id,
                            product_id=line.product_id,
                            qty=line.qty,
                            unit_price=line.unit_price,
                            line_status=line.line_status,  # type: ignore[arg-type]
                            source_rec_id=line.source_rec_id,
                            line_id=line.po_line_id,
                        )
                        for line in approved_lines
                    ]
                    draft_parent = DraftPO(
                        po_id=po.po_id,
                        supplier_id=po.supplier_id,
                        lines=tuple(draft_lines),
                    )
                    child_draft = POBuilder.split(draft_parent, draft_lines)

                    child_po_id = child_draft.po_id
                    child_total = sum((line.value for line in draft_lines), Decimal("0.00"))
                    req_level = (
                        ApprovalLevelRequired.L2.value
                        if child_total >= rules.po_l2_threshold
                        else ApprovalLevelRequired.L1.value
                    )
                    child_status = (
                        POStatus.PENDING_L2.value
                        if req_level == ApprovalLevelRequired.L2.value
                        else POStatus.APPROVED.value
                    )

                    child_po = PurchaseOrder(
                        po_id=child_po_id,
                        parent_po_id=po.po_id,
                        supplier_id=po.supplier_id,
                        run_id=po.run_id,
                        total_value=child_total,
                        required_level=req_level,
                        status=child_status,
                    )
                    child_po.lines = [
                        POLine(
                            po_line_id=uuid.uuid4(),
                            po_id=child_po_id,
                            store_id=dl.store_id,
                            product_id=dl.product_id,
                            qty=dl.qty,
                            unit_price=dl.unit_price,
                            source_rec_id=dl.source_rec_id or uuid.uuid4(),
                            line_status=dl.line_status,
                        )
                        for dl in draft_lines
                    ]
                    self.session.add(child_po)
                    po.status = POStatus.SPLIT.value

            processed_count += 1

        self.session.flush()
        return processed_count

    async def decide(
        self,
        session: AsyncSession,
        req: ApprovalRequest,
        user: AppUser,
    ) -> ApprovalResult:
        """Processes line-level L1 or L2 purchase order approval per SD-10."""
        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(PurchaseOrder.po_id == req.entity_id)
            .with_for_update()
        )
        res = await session.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise NotFound(f"Purchase order {req.entity_id} not found")

        if po.status not in (POStatus.PENDING_L1.value, POStatus.PENDING_L2.value):
            raise ConflictError(f"Purchase order {po.po_id} is in status {po.status}, not PENDING_L1 or PENDING_L2")

        now = datetime.now(UTC)
        child_po_id: UUID | None = None
        target_status = po.status
        decided_line_ids: list[UUID] = []
        source_rec_ids: list[UUID] = []

        # Load business rules for thresholds
        br_res = await session.execute(select(BusinessRule).where(BusinessRule.scope_store_id.is_(None)))
        rules_map = {br.rule_key: br.value for br in br_res.scalars().all()}
        l2_threshold = Decimal(str(rules_map.get("po_l2_threshold", "100000")))

        if po.status == POStatus.PENDING_L1.value:
            store_id = req.store_id or user.store_id
            if not store_id:
                raise ValidationError("store_id is required for L1 PO line decision")

            if user.role == Role.STORE_SUPERVISOR.value:
                if user.store_id != store_id:
                    raise PermissionDenied("Store supervisor can only approve lines for their assigned store")
                if po.l1_deadline and now > po.l1_deadline:
                    raise ConflictError("Approval deadline has passed; lines are escalated")
                lines_to_decide = [ln for ln in po.lines if ln.store_id == store_id and ln.line_status == LineStatus.PENDING.value]
            else:  # Super Admin deciding escalated lines
                lines_to_decide = [ln for ln in po.lines if ln.store_id == store_id and ln.line_status == "ESCALATED"]
                if not lines_to_decide:
                    lines_to_decide = [ln for ln in po.lines if ln.store_id == store_id and ln.line_status == LineStatus.PENDING.value]

            if not lines_to_decide:
                raise ConflictError("No pending lines found for this store on PO")

            edits_map = {e.po_line_id: e.qty for e in req.line_edits}
            for line in lines_to_decide:
                decided_line_ids.append(line.po_line_id)
                source_rec_ids.append(line.source_rec_id)
                if req.decision == "APPROVED":
                    line.line_status = LineStatus.APPROVED.value
                elif req.decision == "EDITED":
                    line.line_status = LineStatus.EDITED.value
                    if line.po_line_id in edits_map:
                        line.qty = edits_map[line.po_line_id]
                elif req.decision == "REJECTED":
                    if not req.reason:
                        raise ValidationError("Reason is required when rejecting purchase order lines")
                    line.line_status = LineStatus.REJECTED.value

            # Record L1 Approval
            appr = Approval(
                approval_id=uuid.uuid4(),
                entity_type="PO",
                entity_id=po.po_id,
                level=ApprovalLevel.L1.value,
                store_id=store_id,
                approver_id=user.user_id,
                decision=req.decision,
                reason=req.reason,
                decided_at=now,
            )
            session.add(appr)

            # Check if all lines are now decided
            pending_or_escalated = [
                ln for ln in po.lines if ln.line_status in (LineStatus.PENDING.value, "ESCALATED")
            ]
            if not pending_or_escalated:
                # Finalize L1
                ok_lines = [
                    ln for ln in po.lines if ln.line_status in (LineStatus.APPROVED.value, LineStatus.EDITED.value)
                ]
                if not ok_lines:
                    po.status = POStatus.REJECTED.value
                    target_status = POStatus.REJECTED.value
                elif len(ok_lines) < len(po.lines):
                    # Some lines rejected -> Split
                    draft_lines = [
                        DraftPOLine(
                            store_id=ln.store_id,
                            product_id=ln.product_id,
                            qty=ln.qty,
                            unit_price=ln.unit_price,
                            line_status=ln.line_status,  # type: ignore[arg-type]
                            source_rec_id=ln.source_rec_id,
                            line_id=ln.po_line_id,
                        )
                        for ln in ok_lines
                    ]
                    draft_parent = DraftPO(
                        po_id=po.po_id,
                        supplier_id=po.supplier_id,
                        lines=tuple(draft_lines),
                    )
                    child_draft = POBuilder.split(draft_parent, draft_lines)
                    child_po_id = child_draft.po_id
                    child_total = sum((dl.value for dl in draft_lines), Decimal("0.00"))

                    next_status = (
                        POStatus.PENDING_L2.value
                        if child_total >= l2_threshold
                        else POStatus.SUBMITTED.value  # Ready/Submitted to supplier
                    )
                    child_po = PurchaseOrder(
                        po_id=child_po_id,
                        parent_po_id=po.po_id,
                        supplier_id=po.supplier_id,
                        run_id=po.run_id,
                        total_value=child_total,
                        required_level=(
                            ApprovalLevelRequired.L2.value
                            if child_total >= l2_threshold
                            else ApprovalLevelRequired.L1.value
                        ),
                        status=next_status,
                    )
                    child_po.lines = [
                        POLine(
                            po_line_id=uuid.uuid4(),
                            po_id=child_po_id,
                            store_id=dl.store_id,
                            product_id=dl.product_id,
                            qty=dl.qty,
                            unit_price=dl.unit_price,
                            source_rec_id=dl.source_rec_id or uuid.uuid4(),
                            line_status=dl.line_status,
                        )
                        for dl in draft_lines
                    ]
                    session.add(child_po)
                    po.status = POStatus.SPLIT.value
                    target_status = next_status
                else:
                    # All lines approved
                    new_total = sum((Decimal(str(ln.qty)) * ln.unit_price for ln in po.lines), Decimal("0.00"))
                    po.total_value = new_total
                    if new_total >= l2_threshold:
                        po.status = POStatus.PENDING_L2.value
                    else:
                        po.status = POStatus.SUBMITTED.value
                    target_status = po.status

        elif po.status == POStatus.PENDING_L2.value:
            if user.role != Role.SUPER_ADMIN.value:
                raise PermissionDenied("Only Super Admin can perform L2 approval")

            appr = Approval(
                approval_id=uuid.uuid4(),
                entity_type="PO",
                entity_id=po.po_id,
                level=ApprovalLevel.L2.value,
                store_id=None,
                approver_id=user.user_id,
                decision=req.decision,
                reason=req.reason,
                decided_at=now,
            )
            session.add(appr)

            if req.decision == "APPROVED":
                po.status = POStatus.SUBMITTED.value
            else:
                po.status = POStatus.REJECTED.value
            target_status = po.status
            source_rec_ids = [ln.source_rec_id for ln in po.lines]

        # Update linked recommendation statuses
        if source_rec_ids:
            new_rec_status = (
                RecStatus.ACCEPTED.value
                if req.decision == "APPROVED"
                else RecStatus.EDITED.value
                if req.decision == "EDITED"
                else RecStatus.REJECTED.value
            )
            await session.execute(
                update(Recommendation)
                .where(Recommendation.rec_id.in_(source_rec_ids))
                .values(status=new_rec_status)
            )

        await session.commit()

        # Invalidate caches
        all_store_ids = list({ln.store_id for ln in po.lines})
        self.cache_service.invalidate_store_keys(all_store_ids, ["inbox", "dash", "inv", "twin"])

        return ApprovalResult(
            po_id=po.po_id,
            status=target_status,
            child_po_id=child_po_id,
            approval_id=appr.approval_id,
        )
