"""Contract-first /api/v1 routes (spec §5, D-32).

The request and response shapes are final so the frontend can generate its types now; the handlers return
501 NOT_IMPLEMENTED until Phase 6 implements them (auth, store scoping, services). Supervisor-facing responses
follow the store-scoping rule encoded in the DTOs (app/domain/schemas/common.py).
"""

from datetime import date
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.errors import NotImplementedYet
from app.domain.schemas.common import Page, PageParams, Priority
from app.domain.schemas.dtos import (
    BatchDTO,
    DashboardSummary,
    InventoryMovementDTO,
    LoginRequest,
    MeDTO,
    MovementType,
    Period,
    POStatus,
    PurchaseOrderDTO,
    RecommendationDetailDTO,
    RecommendationDTO,
    RecStatus,
    RecType,
    RunInfoDTO,
    StockoutRisk,
    StoreDTO,
    StoreInventoryPage,
    TokenResponse,
    TransferOrderDTO,
    TransferStatus,
)

router = APIRouter()
Paging = Annotated[PageParams, Query()]


def _todo() -> NoReturn:
    raise NotImplementedYet()


@router.post("/auth/login", tags=["auth"])
def login(body: LoginRequest) -> TokenResponse:
    _todo()


@router.get("/me", tags=["auth"])
def get_me() -> MeDTO:
    _todo()


@router.get("/stores", tags=["stores"])
def list_stores() -> list[StoreDTO]:
    _todo()


@router.get("/runs/latest", tags=["runs"])
def get_latest_run() -> RunInfoDTO:
    _todo()


@router.get("/dashboard", tags=["dashboard"])
def get_dashboard(store_id: UUID | None = None, period: Period = "LAST_28_DAYS") -> DashboardSummary:
    _todo()


@router.get("/recommendations", tags=["recommendations"])
def list_recommendations(
    paging: Paging,
    store_id: UUID | None = None,
    status: RecStatus | None = None,
    rec_type: Annotated[RecType | None, Query(alias="type")] = None,
    priority: Priority | None = None,
    product_id: UUID | None = None,
) -> Page[RecommendationDTO]:
    _todo()


@router.get("/recommendations/{rec_id}", tags=["recommendations"])
def get_recommendation(rec_id: UUID) -> RecommendationDetailDTO:
    _todo()


@router.get("/stores/{store_id}/inventory", tags=["inventory"])
def get_store_inventory(
    store_id: UUID,
    paging: Paging,
    category: str | None = None,
    risk: StockoutRisk | None = None,
    refill_only: bool = False,
) -> StoreInventoryPage:
    _todo()


@router.get("/stores/{store_id}/inventory/movements", tags=["inventory"])
def list_store_movements(
    store_id: UUID,
    paging: Paging,
    product_id: UUID | None = None,
    movement_type: Annotated[MovementType | None, Query(alias="type")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> Page[InventoryMovementDTO]:
    _todo()


@router.get("/stores/{store_id}/inventory/batches", tags=["inventory"])
def list_store_batches(store_id: UUID, paging: Paging, product_id: UUID | None = None) -> Page[BatchDTO]:
    _todo()


@router.get("/stores/{store_id}/inventory/expiring", tags=["inventory"])
def list_store_expiring(
    store_id: UUID, paging: Paging, within_days: Annotated[int, Query(ge=1, le=60)] = 14
) -> Page[BatchDTO]:
    _todo()


@router.get("/transfers", tags=["transfers"])
def list_transfers(
    paging: Paging,
    store_id: UUID | None = None,
    status: TransferStatus | None = None,
    product_id: UUID | None = None,
) -> Page[TransferOrderDTO]:
    _todo()


@router.get("/transfers/{transfer_id}", tags=["transfers"])
def get_transfer(transfer_id: UUID) -> TransferOrderDTO:
    _todo()


@router.get("/purchase-orders", tags=["purchase-orders"])
def list_purchase_orders(
    paging: Paging, store_id: UUID | None = None, status: POStatus | None = None
) -> Page[PurchaseOrderDTO]:
    _todo()


@router.get("/purchase-orders/{po_id}", tags=["purchase-orders"])
def get_purchase_order(po_id: UUID) -> PurchaseOrderDTO:
    _todo()
