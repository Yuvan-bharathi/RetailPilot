"""Response DTOs of the /api/v1 contract (spec §5). Implemented in Phase 6; stubs return 501 until then (D-32)."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.domain.schemas.common import (
    DTO,
    Counterpart,
    Money,
    Page,
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


class BatchRiskRef(DTO):
    """A batch at risk of expiring before it sells (FEFO, D-31)."""

    batch_no: str
    expiry_date: date
    days_left: int
    batch_qty: int
    at_risk_qty: int


class TransferEvidence(DTO):
    """TRANSFER (surplus or expiry-aware) — design doc §6.

    Scoped per viewer (D-32): donor_surplus and donor_protected_requirement describe the DONOR store's stock, so
    they are filled for the Super Admin and for the donor store's own supervisor, and null for the destination
    supervisor (CLAUDE.md rule 10), who sees the donor as name + offered qty plus the numberless assurance
    `donor_keeps_requirement`.
    """

    kind: Literal["TRANSFER"]
    destination_shortage: int
    donor: Counterpart | None
    donor_surplus: int | None = Field(None, description="Super Admin and the donor store's supervisor only")
    donor_protected_requirement: int | None = Field(
        None, description="Super Admin and the donor store's supervisor only"
    )
    donor_keeps_requirement: bool = Field(
        True, description="Donor stays at or above its own requirement after the transfer (donor protection)"
    )
    transfer_qty: int
    po_remainder_qty: int
    transfer_cost: Money | None
    po_incremental_cost: Money | None
    expected_delivery: date | None
    days_of_cover_before: float
    days_of_cover_after: float
    expiring_batch: BatchRiskRef | None = Field(None, description="Set for an expiry-aware transfer (SD-08)")


NeedReason = Literal["NO_SURPLUS_IN_ANY_STORE", "PARTIAL_SURPLUS", "TRANSFER_NOT_VIABLE"]


class ReorderEvidence(DTO):
    """REORDER — own requirement vs available, and why a PO instead of a transfer (SD-06/07)."""

    kind: Literal["REORDER"]
    reason: NeedReason
    daily_demand: float
    lead_time_days: int
    review_period_days: int
    safety_stock_days: int
    min_display_qty: int
    own_requirement: int
    available: int
    need_qty: int
    transferred_qty: int = Field(
        description="Units covered by transfers (PARTIAL_SURPLUS); the PO is the rest"
    )
    days_of_cover: float
    supplier: SupplierRef
    lost_revenue: Money | None
    lost_profit: Money | None


class CoReplenishEvidence(DTO):
    """CO_REPLENISH — complement of a reordered product (D-02, D-13)."""

    kind: Literal["CO_REPLENISH"]
    linked_product: ProductRef
    support: float
    confidence: float
    lift: float
    daily_demand: float
    review_period_days: int
    own_requirement: int
    available: int
    projected_at_next_review: float = Field(description="available − daily demand × review period")
    supplier: SupplierRef


class ExpiryEvidence(DTO):
    """EXPIRY_ALERT / MARKDOWN — batch that will not sell in time and no store can take it (SD-08)."""

    kind: Literal["EXPIRY"]
    batch: BatchRiskRef
    daily_demand: float
    receivers_checked: int = Field(description="Other stores checked for an expiry-aware transfer")
    markdown_pct: int | None = Field(None, description="MARKDOWN only (extension)")


class AssortmentGapEvidence(DTO):
    """ASSORTMENT_GAP — sells together with a listed product in other stores (SD-05)."""

    kind: Literal["ASSORTMENT_GAP"]
    antecedent: ProductRef
    lift: float
    source_stores: list[StoreRef] = Field(description="Stores where the rule holds (names only)")


ReviewReason = Literal["LOW_CONFIDENCE", "BUDGET", "NO_ELIGIBLE_SUPPLIER"]


class NeedsReviewEvidence(DTO):
    """NEEDS_REVIEW — no automatic action; a person decides (D-04, D-29, SD-09)."""

    kind: Literal["NEEDS_REVIEW"]
    reason: ReviewReason
    own_requirement: int
    available: int
    suggested_qty: int
    detail: str


Evidence = Annotated[
    TransferEvidence
    | ReorderEvidence
    | CoReplenishEvidence
    | ExpiryEvidence
    | AssortmentGapEvidence
    | NeedsReviewEvidence,
    Field(discriminator="kind"),
]


class RecommendationDetailDTO(DTO):
    recommendation: RecommendationDTO
    evidence: Evidence | None


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


class InventorySummary(DTO):
    products: int
    high_risk: int
    medium_risk: int
    refill_needed: int
    near_expiry_qty: int
    shortage_products: int


class StoreInventoryPage(Page[InventoryRowDTO]):
    """Page of inventory rows plus store-wide counts for the summary chips (SD-15 totals)."""

    store: StoreRef
    summary: InventorySummary


MovementType = Literal[
    "SALE", "PO_RECEIPT", "TRANSFER_OUT", "TRANSFER_IN", "SHELF_REFILL", "ADJUSTMENT", "EXPIRY_WRITE_OFF"
]


class InventoryMovementDTO(DTO):
    """One row of the inventory movement ledger (spec §3)."""

    movement_id: UUID
    product: ProductRef
    movement_type: MovementType
    qty: int = Field(description="Signed quantity (+ in, − out)")
    location: Literal["SHELF", "BACKROOM"]
    reference: str | None
    reason: str | None
    occurred_at: datetime = Field(description="When the stock moved (UTC); the ledger's order and cursor key")
    business_date: date = Field(description="The store's trading day (IST) the movement belongs to")


class BatchDTO(DTO):
    """A batch held by the store, in FEFO order, with its expiry risk (D-31)."""

    batch_id: UUID
    product: ProductRef
    batch_no: str
    qty: int
    expiry_date: date
    days_left: int
    fefo_rank: int = Field(description="1 = sells first for this product")
    at_risk_qty: int


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


# --- dashboard widgets (D-46) --------------------------------------------------------------------------------------


class SalesDayDTO(DTO):
    day: date
    revenue: Money
    units: int


class CategoryValueDTO(DTO):
    category: str
    value: Money = Field(description="On-hand units × cost price")


class StockHealthDTO(DTO):
    """Listed store-SKUs by stock-out risk (D-46): days of cover vs lead time and lead + review."""

    high_risk: int
    medium_risk: int
    low_risk: int
    out_of_stock: int = Field(description="Listed store-SKUs with nothing on hand")


class ExpiryDayDTO(DTO):
    day: date
    qty: int
    value: Money


class POStatusCountDTO(DTO):
    status: POStatus
    count: int
    value: Money


class StorePerformanceDTO(DTO):
    store: StoreRef
    revenue: Money
    stockout_rate: float
    high_risk_skus: int


class DashboardInsights(DTO):
    """Series and breakdowns behind the dashboard widgets (D-46). Every list may be empty: the UI shows an empty
    state, never sample figures."""

    store: StoreRef | None
    period: Period
    data_as_of: date | None = Field(description="Run date of the latest successful nightly run")
    forecast_units_per_day: float | None = Field(description="Σ daily demand of the latest run's forecasts")
    sales_trend: list[SalesDayDTO]
    inventory_by_category: list[CategoryValueDTO]
    shelf_value: Money
    backroom_value: Money
    stock_health: StockHealthDTO
    expiry_next_14_days: list[ExpiryDayDTO]
    po_status: list[POStatusCountDTO]
    store_performance: list[StorePerformanceDTO] = Field(
        description="Super Admin, all stores only; else empty"
    )


# --- analytics (D-48) --------------------------------------------------------------------------------------------------


class AbcXyzCellDTO(DTO):
    abc: Literal["A", "B", "C"]
    xyz: Literal["X", "Y", "Z"]
    skus: int


class CategoryPerformanceDTO(DTO):
    category: str
    revenue: Money
    gross_profit: Money
    margin_pct: float
    units: int


class ForecastMixDTO(DTO):
    method: str
    confidence: Literal["HIGH", "LOW"]
    skus: int


class LostSalesItemDTO(DTO):
    store: StoreRef
    product: ProductRef
    lost_units: float
    lost_revenue: Money
    lost_profit: Money


class AnalyticsDTO(DTO):
    """Analytics screen (D-48): classification, category performance, forecast mix and lost sales — all computed."""

    store: StoreRef | None
    period: Period
    data_as_of: date | None
    abc_xyz: list[AbcXyzCellDTO]
    categories: list[CategoryPerformanceDTO]
    forecast_mix: list[ForecastMixDTO]
    top_lost_sales: list[LostSalesItemDTO]
