"""Purchase order routes (spec §5, SD-10, SD-16)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.domain.schemas.common import Page, PageParams
from app.domain.schemas.dtos import POStatus, PurchaseOrderDTO
from app.services.goods_receipt_service import GoodsReceiptRequest, GoodsReceiptService
from app.services.purchase_order_service import PurchaseOrderService

router = APIRouter(tags=["purchase-orders"])
Paging = Annotated[PageParams, Query()]


class ResolvePORequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: str


class CloseShortRequest(BaseModel):
    reason: str


@router.get("/purchase-orders", response_model=Page[PurchaseOrderDTO])
async def list_purchase_orders(
    current_user: CurrentUser,
    session: DbSession,
    paging: Paging,
    store_id: UUID | None = None,
    status: POStatus | None = None,
) -> Page[PurchaseOrderDTO]:
    """Lists purchase orders with lines scoped per viewer role."""
    service = PurchaseOrderService()
    return await service.list_pos(
        session=session,
        user=current_user,
        store_id=store_id,
        status=status,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderDTO)
async def get_purchase_order(
    po_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> PurchaseOrderDTO:
    """Returns single purchase order detail with viewer scoping."""
    service = PurchaseOrderService()
    return await service.get_po(session, po_id, current_user)


@router.post("/purchase-orders/{po_id}/resolve", response_model=PurchaseOrderDTO)
async def resolve_purchase_order(
    po_id: UUID,
    body: ResolvePORequest,
    current_user: CurrentUser,
    session: DbSession,
) -> PurchaseOrderDTO:
    """Super Admin resolves a NEEDS_REVIEW purchase order."""
    service = PurchaseOrderService()
    return await service.resolve_needs_review(
        session=session,
        po_id=po_id,
        decision=body.decision,
        reason=body.reason,
        user=current_user,
    )


@router.post("/purchase-orders/{po_id}/receipts", response_model=PurchaseOrderDTO)
async def receive_goods(
    po_id: UUID,
    body: GoodsReceiptRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> PurchaseOrderDTO:
    """Receives goods delivery against a submitted purchase order (SD-16)."""
    gr_service = GoodsReceiptService()
    await gr_service.receive(session, po_id, body, current_user)
    po_service = PurchaseOrderService()
    return await po_service.get_po(session, po_id, current_user)


@router.post("/purchase-orders/{po_id}/close-short", response_model=PurchaseOrderDTO)
async def close_short(
    po_id: UUID,
    body: CloseShortRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> PurchaseOrderDTO:
    """Super Admin closes short an undelivered balance on a PO."""
    service = PurchaseOrderService()
    return await service.close_short(session, po_id, body.reason, current_user)

