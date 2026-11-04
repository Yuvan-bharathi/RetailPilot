"""Status and type values (spec §2, CD-1, CD-2).

Stored as `text` + `CHECK (col IN (…))`, not native PostgreSQL enums (D-35): adding a value is a one-line
migration that replaces the check constraint. `check_in()` builds the constraint from these classes, so the
database and Python share one list.
"""

from enum import StrEnum


class RecType(StrEnum):
    REORDER = "REORDER"
    TRANSFER = "TRANSFER"
    CO_REPLENISH = "CO_REPLENISH"
    MARKDOWN = "MARKDOWN"
    EXPIRY_ALERT = "EXPIRY_ALERT"
    ASSORTMENT_GAP = "ASSORTMENT_GAP"


class RecStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SUPERSEDED = "SUPERSEDED"


class Priority(StrEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"


class NeedSource(StrEnum):
    SHORTFALL = "SHORTFALL"
    CO_REPLENISH = "CO_REPLENISH"


class NeedReason(StrEnum):
    NO_SURPLUS_IN_ANY_STORE = "NO_SURPLUS_IN_ANY_STORE"
    PARTIAL_SURPLUS = "PARTIAL_SURPLUS"
    TRANSFER_NOT_VIABLE = "TRANSFER_NOT_VIABLE"
    CO_REPLENISH = "CO_REPLENISH"


class ForecastMethod(StrEnum):
    BASELINE = "BASELINE"
    CROSTON = "CROSTON"
    TSB = "TSB"
    IMAPA = "IMAPA"
    ETS = "ETS"


class Confidence(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class AssociationRuleType(StrEnum):
    COMPLEMENT = "COMPLEMENT"
    SUBSTITUTE = "SUBSTITUTE"


class CalendarEventType(StrEnum):
    FESTIVAL = "FESTIVAL"
    SALARY = "SALARY"
    PROMO = "PROMO"
    LOCAL = "LOCAL"


class MovementType(StrEnum):
    SALE = "SALE"
    PO_RECEIPT = "PO_RECEIPT"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    ADJUSTMENT = "ADJUSTMENT"
    EXPIRY_WRITE_OFF = "EXPIRY_WRITE_OFF"
    SHELF_REFILL = "SHELF_REFILL"


class StockLocation(StrEnum):
    SHELF = "SHELF"
    BACKROOM = "BACKROOM"


class MovementReference(StrEnum):
    BILL = "BILL"
    PO = "PO"
    TRANSFER = "TRANSFER"
    RECON = "RECON"


class Role(StrEnum):
    STORE_SUPERVISOR = "STORE_SUPERVISOR"
    SUPER_ADMIN = "SUPER_ADMIN"


class POStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PENDING_L1 = "PENDING_L1"
    PENDING_L2 = "PENDING_L2"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SPLIT = "SPLIT"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalLevelRequired(StrEnum):
    L1 = "L1"
    L2 = "L2"


class LineStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ESCALATED = "ESCALATED"
    SUPERSEDED = "SUPERSEDED"


class TransferStatus(StrEnum):
    PROPOSED = "PROPOSED"
    DEST_ACCEPTED = "DEST_ACCEPTED"
    DONOR_APPROVED = "DONOR_APPROVED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


#: Transfers still in flight (the "active transfers" partial indexes and inbox counts).
ACTIVE_TRANSFER_STATUSES = (
    TransferStatus.PROPOSED,
    TransferStatus.DEST_ACCEPTED,
    TransferStatus.DONOR_APPROVED,
    TransferStatus.DISPATCHED,
)


class ApprovalEntity(StrEnum):
    PO = "PO"
    TRANSFER = "TRANSFER"


class ApprovalLevel(StrEnum):
    L1 = "L1"
    L2 = "L2"
    DEST = "DEST"
    DONOR = "DONOR"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class AgentRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class ToolCallStatus(StrEnum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


def sql_in(values: type[StrEnum] | tuple[StrEnum, ...]) -> str:
    """`'A', 'B', …` for a CHECK / partial-index predicate."""
    return ", ".join(f"'{v.value}'" for v in values)


def check_in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({sql_in(values)})"
