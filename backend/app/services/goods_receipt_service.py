"""Goods receipt service: receives deliveries against submitted POs (SD-16, D-08)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from app.domain.models.enums import LineStatus, MovementType, POStatus, Role
from app.domain.models.inventory import Batch, InventoryMovement, InventoryPosition
from app.domain.models.purchasing import GoodsReceipt, GoodsReceiptLine, PurchaseOrder
from app.domain.models.users import AppUser
from app.services.cache_service import CacheService


class ReceiptLineRequest(BaseModel):
    po_line_id: UUID
    qty: int = Field(gt=0)
    batch_no: str | None = None
    expiry_date: date | None = None


class GoodsReceiptRequest(BaseModel):
    lines: list[ReceiptLineRequest] = Field(min_length=1)
    note: str | None = None


class GoodsReceiptService:
    def __init__(self, cache_service: CacheService | None = None) -> None:
        self.cache_service = cache_service or CacheService()

    async def receive(
        self,
        session: AsyncSession,
        po_id: UUID,
        req: GoodsReceiptRequest,
        user: AppUser,
    ) -> PurchaseOrder:
        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(PurchaseOrder.po_id == po_id)
            .with_for_update()
        )
        res = await session.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise NotFound(f"Purchase order {po_id} not found")

        if po.status not in (POStatus.SUBMITTED.value, POStatus.APPROVED.value):
            raise ConflictError(f"Purchase order is in status {po.status}, not SUBMITTED/APPROVED")

        line_map = {pl.po_line_id: pl for pl in po.lines}
        receiving_store_ids: set[UUID] = set()

        for r_line in req.lines:
            pl = line_map.get(r_line.po_line_id)
            if not pl:
                raise NotFound(f"PO Line {r_line.po_line_id} not part of PO {po_id}")

            if user.role == Role.STORE_SUPERVISOR.value and pl.store_id != user.store_id:
                raise PermissionDenied("Store supervisor can only receive lines belonging to their own store")

            receiving_store_ids.add(pl.store_id)

            if pl.line_status not in (LineStatus.APPROVED.value, LineStatus.EDITED.value):
                raise ConflictError(
                    f"PO Line {pl.po_line_id} is in status {pl.line_status}, not APPROVED/EDITED"
                )

            if pl.received_qty + r_line.qty > pl.qty:
                raise ValidationError(
                    f"Received qty {pl.received_qty + r_line.qty} exceeds ordered qty {pl.qty} for line {pl.po_line_id}"
                )

        now = datetime.now(UTC)
        store_id = next(iter(receiving_store_ids))

        receipt = GoodsReceipt(
            receipt_id=uuid.uuid4(),
            po_id=po_id,
            store_id=store_id,
            received_by=user.user_id,
            received_at=now,
            note=req.note,
        )
        session.add(receipt)

        ledger_movements: list[InventoryMovement] = []

        for r_line in req.lines:
            pl = line_map[r_line.po_line_id]
            batch_id: UUID | None = None

            if r_line.batch_no and r_line.expiry_date:
                # Upsert batch
                b_stmt = select(Batch).where(
                    Batch.store_id == pl.store_id,
                    Batch.product_id == pl.product_id,
                    Batch.batch_no == r_line.batch_no,
                )
                b_res = await session.execute(b_stmt)
                batch_obj = b_res.scalar_one_or_none()
                if batch_obj:
                    batch_obj.qty += r_line.qty
                    batch_id = batch_obj.batch_id
                else:
                    batch_id = uuid.uuid4()
                    batch_obj = Batch(
                        batch_id=batch_id,
                        store_id=pl.store_id,
                        product_id=pl.product_id,
                        batch_no=r_line.batch_no,
                        expiry_date=r_line.expiry_date,
                        qty=r_line.qty,
                    )
                    session.add(batch_obj)

            gr_line = GoodsReceiptLine(
                receipt_line_id=uuid.uuid4(),
                receipt_id=receipt.receipt_id,
                po_line_id=pl.po_line_id,
                qty=r_line.qty,
                batch_no=r_line.batch_no,
                expiry_date=r_line.expiry_date,
            )
            session.add(gr_line)

            pl.received_qty += r_line.qty

            # Prepare ledger movement
            ledger_movements.append(
                InventoryMovement(
                    movement_id=uuid.uuid4(),
                    store_id=pl.store_id,
                    product_id=pl.product_id,
                    batch_id=batch_id,
                    movement_type=MovementType.PO_RECEIPT.value,
                    qty=r_line.qty,
                    location="BACKROOM",
                    reference_type="PO",
                    reference_id=po_id,
                    reason="goods receipt",
                    user_id=user.user_id,
                    business_date=now.date(),
                    occurred_at=now,
                )
            )

            # Update inventory position: add to backroom, subtract from incoming
            pos_stmt = select(InventoryPosition).where(
                InventoryPosition.store_id == pl.store_id,
                InventoryPosition.product_id == pl.product_id,
            )
            pos_res = await session.execute(pos_stmt)
            pos_obj = pos_res.scalar_one_or_none()
            if pos_obj:
                pos_obj.backroom_qty += r_line.qty
                pos_obj.incoming = max(0, pos_obj.incoming - r_line.qty)
            else:
                pos_obj = InventoryPosition(
                    store_id=pl.store_id,
                    product_id=pl.product_id,
                    shelf_qty=0,
                    backroom_qty=r_line.qty,
                    incoming=0,
                    reserved=0,
                )
                session.add(pos_obj)

        for mov in ledger_movements:
            session.add(mov)

        # Check if fully received
        active_lines = [
            ln for ln in po.lines if ln.line_status in (LineStatus.APPROVED.value, LineStatus.EDITED.value)
        ]
        if all(ln.received_qty >= ln.qty for ln in active_lines):
            po.status = POStatus.RECEIVED.value

        await session.commit()
        await session.refresh(po)

        self.cache_service.invalidate_store_keys(list(receiving_store_ids), ["inbox", "dash", "inv", "twin"])
        return po
