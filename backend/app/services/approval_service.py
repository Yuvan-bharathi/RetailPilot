"""Approval service: line-level decisions, deadline enforcement, and PO splitting (SD-10, SD-14)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.domain.models.enums import ApprovalLevelRequired, LineStatus, POStatus
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.repositories.purchasing_repo import PurchasingRepo
from app.services.cache_service import CacheService
from app.tools.po_builder import POBuilder
from app.tools.types import DraftPO, DraftPOLine

logger = logging.getLogger(__name__)


class ApprovalService:
    def __init__(self, session: Session, cache_service: CacheService | None = None) -> None:
        self.session = session
        self.cache_service = cache_service or CacheService()
        self.purchasing_repo = PurchasingRepo(session)

    def expire_overdue(self, now: datetime | None = None) -> int:
        """Enforces approval deadlines for overdue PENDING_L1 POs (SD-14)."""
        if now is None:
            now = datetime.now(UTC)

        rules = self.purchasing_repo.get_business_rules()
        action = rules.deadline_action

        # Find overdue PENDING_L1 POs (FOR UPDATE SKIP LOCKED in production)
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
                logger.info(
                    "Escalated %d lines on PO %s to Super Admin", len(line_ids), po.po_id
                )
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
                    # Split into child PO with approved lines
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
