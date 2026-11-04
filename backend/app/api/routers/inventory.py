"""Store inventory and movement ledger routes (spec §5, SD-15, D-37)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.domain.schemas.common import CursorPage, CursorParams, Page, PageParams
from app.domain.schemas.dtos import (
    BatchDTO,
    InventoryMovementDTO,
    MovementType,
    StockoutRisk,
    StoreInventoryPage,
)
from app.services.inventory_view_service import InventoryViewService

router = APIRouter(tags=["inventory"])
Paging = Annotated[PageParams, Query()]
CursorPaging = Annotated[CursorParams, Query()]


@router.get("/stores/{store_id}/inventory", response_model=StoreInventoryPage)
async def get_store_inventory(
    store_id: UUID,
    paging: Paging,
    current_user: CurrentUser,
    session: DbSession,
    category: str | None = None,
    risk: StockoutRisk | None = None,
    refill_only: bool = False,
) -> StoreInventoryPage:
    """Store inventory grid with stockout risk rank sort and summary totals (SD-15)."""
    service = InventoryViewService()
    return await service.get_view(
        session=session,
        store_id=store_id,
        user=current_user,
        category=category,
        risk=risk,
        refill_only=refill_only,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
    )


@router.get("/stores/{store_id}/inventory/movements", response_model=CursorPage[InventoryMovementDTO])
async def list_store_movements(
    store_id: UUID,
    paging: CursorPaging,
    current_user: CurrentUser,
    session: DbSession,
    product_id: UUID | None = None,
    movement_type: Annotated[MovementType | None, Query(alias="type")] = None,
    date_from: Annotated[
        date | None, Query(alias="from", description="First business_date (IST), inclusive")
    ] = None,
    date_to: Annotated[
        date | None, Query(alias="to", description="Last business_date (IST), inclusive")
    ] = None,
) -> CursorPage[InventoryMovementDTO]:
    """Movement ledger, newest first (occurred_at DESC, movement_id DESC), keyset-paged (D-37)."""
    service = InventoryViewService()
    return await service.list_movements(
        session=session,
        store_id=store_id,
        user=current_user,
        cursor_token=paging.cursor,
        page_size=paging.page_size,
        product_id=product_id,
        movement_type=movement_type,
        date_from=date_from,
        date_to=date_to,
        q=paging.q,
    )


@router.get("/stores/{store_id}/inventory/batches", response_model=Page[BatchDTO])
async def list_store_batches(
    store_id: UUID,
    paging: Paging,
    current_user: CurrentUser,
    session: DbSession,
    product_id: UUID | None = None,
) -> Page[BatchDTO]:
    """Returns store batches in FEFO order with expiry risk."""
    service = InventoryViewService()
    return await service.list_batches(
        session=session,
        store_id=store_id,
        user=current_user,
        product_id=product_id,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/stores/{store_id}/inventory/expiring", response_model=Page[BatchDTO])
async def list_store_expiring(
    store_id: UUID,
    paging: Paging,
    current_user: CurrentUser,
    session: DbSession,
    within_days: Annotated[int, Query(ge=1, le=60)] = 14,
) -> Page[BatchDTO]:
    """Returns store batches expiring within N days."""
    service = InventoryViewService()
    return await service.list_expiring(
        session=session,
        store_id=store_id,
        user=current_user,
        within_days=within_days,
        page=paging.page,
        page_size=paging.page_size,
    )
