"""Value types and input protocols for the deterministic tools (decision D-19).

Tools never import ORM models. Where the spec names an ORM type as a parameter, the tools accept a read-only
Protocol, so both ORM objects (Phase 2) and the plain dataclasses below satisfy it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID, uuid4

Priority = Literal["HIGH", "NORMAL"]
NeedReason = Literal["NO_SURPLUS_IN_ANY_STORE", "PARTIAL_SURPLUS", "TRANSFER_NOT_VIABLE", "CO_REPLENISH"]
LineStatus = Literal["PENDING", "APPROVED", "EDITED", "REJECTED", "EXPIRED", "ESCALATED", "SUPERSEDED"]
DeadlineAction = Literal["ESCALATE", "EXPIRE"]

# Line statuses that still count towards a PO's value and continue to the supplier.
ACTIVE_LINE_STATUSES: frozenset[str] = frozenset({"PENDING", "APPROVED", "EDITED", "ESCALATED"})

# ---------------------------------------------------------------------------------------------------------------
# Input protocols (satisfied by ORM models and by the dataclasses below)
# ---------------------------------------------------------------------------------------------------------------


class TransferRouteLike(Protocol):
    """A transfer route between two own stores (CD-2 TransferRoute)."""

    @property
    def fixed_cost(self) -> Decimal: ...
    @property
    def per_unit_cost(self) -> Decimal: ...
    @property
    def handling_cost_per_unit(self) -> Decimal: ...
    @property
    def transit_days(self) -> int: ...


class SupplyTermsLike(Protocol):
    """Terms of the supplier serving one store for one product (SD-06 StoreSupplyTerms)."""

    @property
    def supplier_id(self) -> UUID: ...
    @property
    def lead_time_days(self) -> int: ...
    @property
    def delivery_charge(self) -> Decimal: ...
    @property
    def unit_cost(self) -> Decimal: ...


class BatchLike(Protocol):
    """A stock batch with an expiry date (CD-1 Batch)."""

    @property
    def batch_id(self) -> UUID: ...
    @property
    def qty(self) -> int: ...
    @property
    def expiry_date(self) -> date: ...


# ---------------------------------------------------------------------------------------------------------------
# Concrete inputs
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Route:
    fixed_cost: Decimal
    per_unit_cost: Decimal
    handling_cost_per_unit: Decimal
    transit_days: int


@dataclass(frozen=True, slots=True)
class StoreSupplyTerms:
    supplier_id: UUID
    lead_time_days: int
    delivery_charge: Decimal
    unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class BatchInfo:
    batch_id: UUID
    qty: int
    expiry_date: date


@dataclass(frozen=True, slots=True)
class IncomingItem:
    """Committed incoming stock (approved PO line or dispatched transfer) with its expected arrival date."""

    qty: int
    expected_date: date


@dataclass(frozen=True, slots=True)
class StoreState:
    """One store's position for one product in a nightly run (SD-06). Only HIGH-confidence states (D-04)."""

    store_id: UUID
    requirement: int
    available: int
    daily_demand: float
    review_period_days: int = 0

    @property
    def surplus(self) -> int:
        return self.available - self.requirement

    @property
    def days_of_cover(self) -> float:
        return self.available / max(self.daily_demand, 0.01)


@dataclass(frozen=True, slots=True)
class CostInputs:
    """Cost settings for one product's transfer-vs-PO decision (SD-07)."""

    terms_by_store: Mapping[UUID, SupplyTermsLike]
    order_fixed_cost: Decimal
    holding_cost_rate_per_day: Decimal
    expiry_risk_pct: Decimal
    is_perishable: bool
    days_to_sell_cap: int
    planned_supplier_stores: frozenset[tuple[UUID, UUID]] = frozenset()


# ---------------------------------------------------------------------------------------------------------------
# Outputs of the transfer engine
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransferProposal:
    from_store: UUID
    to_store: UUID
    product_id: UUID
    qty: int
    transfer_cost: Decimal
    po_cost_avoided: Decimal
    transit_days: int
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PONeed:
    store_id: UUID
    product_id: UUID
    qty: int
    priority: Priority
    reason: NeedReason
    supplier_id: UUID
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransferPlan:
    transfers: tuple[TransferProposal, ...] = ()
    po_needs: tuple[PONeed, ...] = ()


# ---------------------------------------------------------------------------------------------------------------
# Purchasing
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierOffer:
    """A supplier's offer for one product delivered to one store."""

    supplier_id: UUID
    product_id: UUID
    unit_price: Decimal
    lead_time_days: int
    moq: int
    order_pack_size: int
    available: bool = True


@dataclass(frozen=True, slots=True)
class ReplenishmentNeed:
    """The tools' view of a ReplenishmentNeed row (CD-1)."""

    store_id: UUID
    product_id: UUID
    qty: int
    run_date: date
    required_by: date
    priority: Priority = "NORMAL"
    reason: NeedReason = "NO_SURPLUS_IN_ANY_STORE"
    preferred_supplier_id: UUID | None = None
    abc_class: str | None = None
    source_rec_id: UUID | None = None
    need_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class DraftPOLine:
    store_id: UUID
    product_id: UUID
    qty: int
    unit_price: Decimal
    order_pack_size: int = 1
    moq: int = 0
    priority: Priority = "NORMAL"
    abc_class: str | None = None
    source_rec_id: UUID | None = None
    line_status: LineStatus = "PENDING"
    line_id: UUID = field(default_factory=uuid4)

    @property
    def value(self) -> Decimal:
        return self.unit_price * self.qty


@dataclass(frozen=True, slots=True)
class DraftPO:
    supplier_id: UUID
    lines: tuple[DraftPOLine, ...]
    flags: tuple[str, ...] = ()
    parent_po_id: UUID | None = None
    po_id: UUID = field(default_factory=uuid4)

    @property
    def active_lines(self) -> tuple[DraftPOLine, ...]:
        return tuple(line for line in self.lines if line.line_status in ACTIVE_LINE_STATUSES)

    @property
    def total_value(self) -> Decimal:
        """Unrounded value of the active lines (round with numeric.money() for output)."""
        return sum((line.value for line in self.active_lines), Decimal(0))

    @property
    def store_ids(self) -> tuple[UUID, ...]:
        return tuple(sorted({line.store_id for line in self.lines}))


@dataclass(frozen=True, slots=True)
class BudgetTrimResult:
    """Outcome of POBuilder.prioritise_within_budget (D-29).

    `reduced`: ids of lines whose qty was lowered to fit; `skipped`: lines removed because not even the MOQ /
    one pack fits — the PO agent turns each into a NEEDS_REVIEW recommendation with reason BUDGET.
    """

    po: DraftPO
    reduced: tuple[UUID, ...] = ()
    skipped: tuple[DraftPOLine, ...] = ()


@dataclass(frozen=True, slots=True)
class POLineEdit:
    po_line_id: UUID
    qty: int


@dataclass(frozen=True, slots=True)
class BusinessRules:
    po_l2_threshold: Decimal
    weekly_budget: Decimal
    order_fixed_cost: Decimal = Decimal(0)
    l1_deadline_hours: int = 24
    deadline_action: DeadlineAction = "ESCALATE"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()

    @property
    def budget_exceeded(self) -> bool:
        return "BUDGET_EXCEEDED" in self.errors


# ---------------------------------------------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BasketQualityRules:
    exclude_returns: bool = True
    exclude_voided: bool = True
    max_qty_per_line: int = 24  # default bulk-line limit (business rule basket.max_qty_per_line)
    exclude_promo_days: bool = True
    # per-category overrides (business rule basket.max_qty_per_line_by_category, D-27)
    max_qty_per_line_by_category: Mapping[str, int] = field(default_factory=dict)

    def limit_for(self, category: str | None) -> int:
        if category is None:
            return self.max_qty_per_line
        return self.max_qty_per_line_by_category.get(category, self.max_qty_per_line)


@dataclass(frozen=True, slots=True)
class GapSuggestion:
    store_id: UUID
    product_id: UUID
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BatchRisk:
    batch_id: UUID
    expiry_date: date
    days_left: int
    qty: int
    sellable: int
    at_risk: int
