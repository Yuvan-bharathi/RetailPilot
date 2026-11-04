"""Transfer routes (spec §5, SD-12)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.domain.schemas.common import Page, PageParams
from app.domain.schemas.dtos import TransferOrderDTO, TransferStatus
from app.services.transfer_service import TransferService

router = APIRouter(tags=["transfers"])
Paging = Annotated[PageParams, Query()]


class RejectTransferRequest(BaseModel):
    reason: str = Field(min_length=1)


class ReceiveTransferRequest(BaseModel):
    received_qty: int = Field(ge=0)


@router.get("/transfers", response_model=Page[TransferOrderDTO])
async def list_transfers(
    current_user: CurrentUser,
    session: DbSession,
    paging: Paging,
    store_id: UUID | None = None,
    status: TransferStatus | None = None,
    product_id: UUID | None = None,
) -> Page[TransferOrderDTO]:
    """Lists stock transfers for the store or chain with paging."""
    service = TransferService()
    return await service.list_transfers(
        session=session,
        user=current_user,
        store_id=store_id,
        status=status,
        product_id=product_id,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/transfers/{transfer_id}", response_model=TransferOrderDTO)
async def get_transfer(
    transfer_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> TransferOrderDTO:
    """Returns single transfer order detail with viewer scoping."""
    service = TransferService()
    return await service.get_transfer(session, transfer_id, current_user)


@router.post("/transfers/{transfer_id}/accept", response_model=TransferOrderDTO)
async def accept_transfer(
    transfer_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> TransferOrderDTO:
    """Destination store supervisor accepts the incoming transfer (SD-12 step 1)."""
    service = TransferService()
    return await service.accept(session, transfer_id, current_user)


@router.post("/transfers/{transfer_id}/approve-release", response_model=TransferOrderDTO)
async def approve_release(
    transfer_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> TransferOrderDTO:
    """Donor store supervisor approves releasing stock (SD-12 step 2)."""
    service = TransferService()
    return await service.approve_release(session, transfer_id, current_user)


@router.post("/transfers/{transfer_id}/reject", response_model=TransferOrderDTO)
async def reject_transfer(
    transfer_id: UUID,
    body: RejectTransferRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> TransferOrderDTO:
    """Destination or donor supervisor rejects the transfer."""
    service = TransferService()
    return await service.reject(session, transfer_id, body.reason, current_user)


@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferOrderDTO)
async def dispatch_transfer(
    transfer_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> TransferOrderDTO:
    """Donor store supervisor marks the stock as dispatched (SD-12 step 4)."""
    service = TransferService()
    return await service.dispatch(session, transfer_id, current_user)


@router.post("/transfers/{transfer_id}/receive", response_model=TransferOrderDTO)
async def receive_transfer(
    transfer_id: UUID,
    body: ReceiveTransferRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> TransferOrderDTO:
    """Destination store supervisor confirms receipt quantity (SD-12 step 5)."""
    service = TransferService()
    return await service.receive(session, transfer_id, body.received_qty, current_user)
