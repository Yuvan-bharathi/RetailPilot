"""Ingestion DTOs, data transfer records, and PosSource contract (SD-02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RawBillLine:
    bill_id: UUID
    line_no: int
    txn_datetime: datetime
    txn_date: date
    store_id: UUID
    product_id: UUID
    qty: int
    unit_price: Decimal
    discount: Decimal
    is_return: bool = False
    is_voided: bool = False
    is_promo_day: bool = False


@dataclass(frozen=True, slots=True)
class RawStockRow:
    store_id: UUID
    product_id: UUID
    snapshot_date: date
    shelf_qty: int
    backroom_qty: int
    closing_on_hand: int


@dataclass(frozen=True, slots=True)
class RawBatchRow:
    batch_id: UUID
    store_id: UUID
    product_id: UUID
    batch_no: str
    qty: int
    expiry_date: date
    received_date: date | None = None


@dataclass(frozen=True, slots=True)
class RowError:
    row_ref: str
    reason: str


@dataclass
class ValidationReport:
    valid_rows: int = 0
    stale_skus: list[tuple[UUID, UUID]] = field(default_factory=list)  # (store_id, product_id)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"valid={self.valid_rows}, stale={len(self.stale_skus)}, errors={len(self.errors)}"


class PosSource(Protocol):
    """Data source adapter interface for POS data (SD-02)."""

    def fetch_sales(self, store_id: UUID, day: date) -> list[RawBillLine]: ...
    def fetch_stock_snapshot(self, store_id: UUID, day: date) -> list[RawStockRow]: ...
    def fetch_batches(self, store_id: UUID) -> list[RawBatchRow]: ...
