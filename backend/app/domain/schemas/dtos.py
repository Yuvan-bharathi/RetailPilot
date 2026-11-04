"""Response DTOs of the /api/v1 contract (spec §5). Implemented in Phase 6; stubs return 501 until then (D-32)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.schemas.common import (
    DTO,
    Counterpart,
    Money,
    Priority,
    ProductRef,
    Role,
    StoreRef,
    SupplierRef,
)

# --- identity -------------------------------------------------------------------------------------------------------


class LoginRequest(DTO):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(DTO):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MeDTO(DTO):
    user_id: UUID
    name: str
    role: Role
    store: StoreRef | None = Field(description="The supervisor's own store; null for Super Admin")


class StoreDTO(DTO):
    store_id: UUID
    code: str
    name: str
    region: str
    store_type: str


class RunInfoDTO(DTO):
    """Latest successful nightly run — the 'Data as of last run' in the header."""

    run_id: UUID
    run_date: date
    status: Literal["SUCCESS", "PARTIAL"]
    finished_at: datetime


# --- dashboard ------------------------------------------------------------------------------------------------------

Period = Literal["TODAY", "LAST_7_DAYS", "LAST_28_DAYS", "MONTH_TO_DATE"]


class MoverDTO(DTO):
    product: ProductRef
    units: int
    revenue: Money


class DashboardSummary(DTO):
    store: StoreRef | None = Field(description="null = all stores (Super Admin)")
    period: Period
    revenue: Money
    gross_profit: Money
    margin_pct: float
    stockout_rate: float
    lost_revenue: Money
    lost_profit: Money
    inventory_value: Money
    near_expiry_value: Money
    pending_recommendations: int
    pending_purchase_orders: int
    active_transfers: int
    fast_movers: list[MoverDTO]
    slow_movers: list[MoverDTO]


# --- recommendations ------------------------------------------------------------------------------------------------

RecType = Literal["REORDER", "TRANSFER", "CO_REPLENISH", "MARKDOWN", "EXPIRY_ALERT", "ASSORTMENT_GAP"]
RecStatus = Literal["PENDING", "ACCEPTED", "EDITED", "REJECTED", "NEEDS_REVIEW", "SUPERSEDED"]


class RecommendationDTO(DTO):
    rec_id: UUID
    run_id: UUID
    store: StoreRef
    product: ProductRef
    rec_type: RecType
    status: RecStatus
    priority: Priority
    qty: int
    lost_revenue: Money | None = None
    explanation: str | None = None
    counterpart: Counterpart | None = Field(
        None, description="Other store of a transfer (donor or destination): name + quantity only"
    )
    created_at: datetime


class TransferEvidenceDTO(DTO):
    """Evidence panel of a transfer / PO-remainder recommendation (design doc §6).

    donor_surplus and donor_protected_requirement describe ANOTHER store's stock: Super Admin only — null for
    Store Supervisors (CLAUDE.md rule 10; they see the donor as `counterpart` name + offered qty).
    """

    destination_shortage: int
    donor: Counterpart | None
    donor_surplus: int | None = Field(None, description="Super Admin only")
    donor_protected_requirement: int | None = Field(None, description="Super Admin only")
    transfer_qty: int
    po_remainder_qty: int
    transfer_cost: Money | None
    po_incremental_cost: Money | None
    expected_delivery: date | None
    days_of_cover_before: float
    days_of_cover_after: float


class RecommendationDetailDTO(DTO):
    recommendation: RecommendationDTO
    evidence: TransferEvidenceDTO | None
    reason: str | None = Field(None, description="NO_SURPLUS_IN_ANY_STORE, PARTIAL_SURPLUS, BUDGET, …")


# --- store inventory (SD-15) ----------------------------------------------------------------------------------------

StockoutRisk = Literal["HIGH", "MEDIUM", "LOW"]


class InventoryRowDTO(DTO):
    product: ProductRef
    shelf_qty: int
    shelf_min: int
    backroom_qty: int
    incoming: int
    reserved: int
    available: int
    own_requirement: int
    surplus_or_shortage: int = Field(description="available − own requirement (negative = shortage)")
    days_of_cover: float
    stockout_risk: StockoutRisk
    near_expiry_qty: int
    pending_transfer_in: int
    pending_transfer_out: int
    refill_from_backroom: bool


# --- transfers ------------------------------------------------------------------------------------------------------

TransferStatus = Literal[
    "PROPOSED",
    "DEST_ACCEPTED",
    "DONOR_APPROVED",
    "DISPATCHED",
    "RECEIVED",
    "REJECTED",
    "CANCELLED",
    "SUPERSEDED",
]


class TransferOrderDTO(DTO):
    transfer_id: UUID
    product: ProductRef
    from_store: StoreRef
    to_store: StoreRef
    qty: int
    status: TransferStatus
    is_expiry_aware: bool
    transit_days: int
    transfer_cost: Money | None = Field(
        None, description="Incremental transfer cost; visible to both roles (not another store's stock data)"
    )
    created_at: datetime
    received_qty: int | None = None


# --- purchase orders ------------------------------------------------------------------------------------------------

POStatus = Literal[
    "DRAFT",
    "NEEDS_REVIEW",
    "PENDING_L1",
    "PENDING_L2",
    "APPROVED",
    "REJECTED",
    "SPLIT",
    "SUBMITTED",
    "RECEIVED",
    "SUPERSEDED",
]
LineStatus = Literal["PENDING", "APPROVED", "EDITED", "REJECTED", "EXPIRED", "ESCALATED", "SUPERSEDED"]


class POLineDTO(DTO):
    po_line_id: UUID
    store: StoreRef
    product: ProductRef
    qty: int
    unit_price: Money
    line_value: Money
    line_status: LineStatus
    received_qty: int = 0


class PurchaseOrderDTO(DTO):
    po_id: UUID
    supplier: SupplierRef
    status: POStatus
    required_level: Literal["L1", "L2"]
    total_value: Money
    l1_deadline: datetime | None
    parent_po_id: UUID | None
    flags: list[str]
    lines: list[POLineDTO] = Field(description="Lines the user may see (a supervisor: own store only)")
    other_store_lines: list[Counterpart] = Field(
        default_factory=list, description="Other stores on a consolidated PO: name + total qty only"
    )
    created_at: datetime
