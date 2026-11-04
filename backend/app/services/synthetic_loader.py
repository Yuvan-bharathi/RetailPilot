"""Load the synthetic dataset (data/synthetic) into PostgreSQL — master data and history (Phase 4b, D-41, D-47).

- Master data (stores, products, suppliers, offers, store terms, store listings, routes, calendar) is upserted
  (ON CONFLICT DO NOTHING), so it can run after `scripts.seed`, which creates the same stores.
- Bulk history uses PostgreSQL COPY (D-41) straight into the partitioned parents: bills, bill lines, daily stock
  snapshots and the movement ledger.
- Ledger history (rule 8): per store-SKU an opening balance on the first day, then per day the SALE total (sale
  lines only), each PO_RECEIPT and EXPIRY_WRITE_OFF; wherever the replay differs from the POS closing stock, a
  reconciliation ADJUSTMENT (reference RECON) — e.g. the planted stock mismatch. The final position (shelf /
  backroom) is the last snapshot and equals the sum of the movements; `incoming` = open orders not yet received.
- Days after `through` are left for the nightly ingestion (SD-02).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models import (
    Batch,
    CalendarEvent,
    InventoryPosition,
    Product,
    Store,
    StoreProduct,
    Supplier,
    SupplierProduct,
    SupplierStoreTerms,
    TransferRoute,
)
from data.synthetic.reader import Dataset

IST = timedelta(hours=5, minutes=30)
NAMESPACE = uuid.UUID("6f1d3c3a-6c1e-4a59-9f43-0a3b7c1d2e01")


@dataclass(frozen=True)
class LoadReport:
    stores: int
    products: int
    bills: int
    lines: int
    snapshots: int
    movements: int
    reconciliation_adjustments: int
    through: date


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """IST local time of `day` as a UTC timestamp."""
    return datetime.combine(day, time(hour, minute), tzinfo=UTC) - IST


def _mid(*parts: object) -> UUID:
    return uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts))


def _upsert(session: Session, model: Any, frame: pd.DataFrame, columns: list[str], **extra: Any) -> int:
    rows = [{c: row[c] for c in columns} | extra for row in frame.to_dict("records")]
    if not rows:
        return 0
    table: Table = model.__table__
    for start in range(0, len(rows), 1000):
        session.execute(insert(table).values(rows[start : start + 1000]).on_conflict_do_nothing())
    return len(rows)


def _rows(frame: pd.DataFrame) -> list[Any]:
    """Row tuples with attribute access (pandas types them loosely)."""
    return list(frame.itertuples(index=False))


def _copy(session: Session, table: str, columns: list[str], rows: Any) -> int:
    count = 0
    dbapi: Any = session.connection().connection.dbapi_connection  # psycopg 3 connection (COPY API)
    assert dbapi is not None
    with dbapi.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def load_synthetic(session: Session, ds: Dataset, through: date | None = None) -> LoadReport:
    """Load master data and all history up to and including `through` (default: the dataset's last day)."""
    through = through or date.fromisoformat(ds.manifest["end_date"])

    # --- master data -------------------------------------------------------------------------------------------
    n_stores = _upsert(
        session, Store, ds.stores, ["store_id", "code", "name", "region", "store_type", "display_capacity"]
    )
    products = ds.products.astype(object).where(ds.products.notna(), None)
    n_products = _upsert(
        session,
        Product,
        products,
        [
            "product_id",
            "sku",
            "name",
            "category",
            "brand",
            "cost_price",
            "selling_price",
            "pack_size",
            "shelf_life_days",
        ],
    )
    _upsert(
        session, Supplier, ds.suppliers, ["supplier_id", "name", "default_lead_time_days"], is_active=True
    )
    _upsert(
        session,
        SupplierProduct,
        ds.supplier_products,
        ["supplier_id", "product_id", "price", "lead_time_days", "moq", "order_pack_size"],
    )
    _upsert(
        session,
        SupplierStoreTerms,
        ds.supplier_store_terms,
        ["supplier_id", "store_id", "lead_time_days", "delivery_charge"],
    )
    _upsert(
        session,
        StoreProduct,
        ds.store_products,
        [
            "store_id",
            "product_id",
            "preferred_supplier_id",
            "min_display_qty",
            "safety_stock_days",
            "review_period_days",
            "is_listed",
        ],
    )
    _upsert(
        session,
        TransferRoute,
        ds.transfer_routes,
        [
            "from_store_id",
            "to_store_id",
            "fixed_cost",
            "per_unit_cost",
            "handling_cost_per_unit",
            "transit_days",
        ],
    )
    _upsert(
        session,
        CalendarEvent,
        ds.calendar_events,
        ["event_id", "event_date", "event_type", "region", "description"],
    )
    session.flush()

    # --- sales and snapshots (COPY) ----------------------------------------------------------------------------
    bills = ds.sales_bills[ds.sales_bills["txn_date"] <= through]
    n_bills = _copy(
        session,
        "sales_transaction",
        ["bill_id", "store_id", "txn_datetime", "txn_date", "total_amount"],
        bills[["bill_id", "store_id", "txn_datetime", "txn_date", "total_amount"]].itertuples(
            index=False, name=None
        ),
    )
    line_cols = ["bill_id", "line_no", "txn_date", "store_id", "product_id", "qty", "unit_price", "discount",
                 "is_return", "is_voided", "is_promo_day"]  # fmt: skip
    lines = ds.sales_lines[ds.sales_lines["txn_date"] <= through]
    n_lines = _copy(session, "sales_line", line_cols, (
        (*r[:5], int(r[5]), *r[6:8], bool(r[8]), bool(r[9]), bool(r[10]))
        for r in lines[line_cols].itertuples(index=False, name=None)
    ))  # fmt: skip
    snaps = ds.stock_snapshots[ds.stock_snapshots["snapshot_date"] <= through]
    snap_cols = ["store_id", "product_id", "snapshot_date", "shelf_qty", "backroom_qty", "closing_on_hand"]
    n_snaps = _copy(session, "inventory_daily_snapshot", snap_cols, (
        (r[0], r[1], r[2], int(r[3]), int(r[4]), int(r[5]))
        for r in snaps[snap_cols].itertuples(index=False, name=None)
    ))  # fmt: skip

    # --- movement ledger --------------------------------------------------------------------------------------
    sold = (
        lines[~lines["is_return"] & ~lines["is_voided"]]
        .groupby(["store_id", "product_id", "txn_date"])["qty"]
        .sum()
    )
    received = ds.receipts[ds.receipts["receipt_date"] <= through]
    written = ds.write_offs[ds.write_offs["write_off_date"] <= through]
    rec_by_day = received.groupby(["store_id", "product_id", "receipt_date"])["qty"].sum()
    wo_by_day = written.groupby(["store_id", "product_id", "write_off_date"])["qty"].sum()
    movements: list[tuple[Any, ...]] = []
    adjustments = 0

    def move(store: UUID, product: UUID, kind: str, qty: int, loc: str, at: datetime, ref: str | None,
             reason: str | None, *key: object) -> None:  # fmt: skip
        if qty:
            movements.append((_mid(kind, store, product, *key), at, (at + IST).date(), store, product, kind, qty, loc,
                              ref, reason))  # fmt: skip

    for r in _rows(received):
        move(r.store_id, r.product_id, "PO_RECEIPT", int(r.qty), "BACKROOM", _at(r.receipt_date, 9), "PO",
             f"Supplier delivery, batch {r.batch_no}", r.receipt_id)  # fmt: skip
    for r in _rows(written):
        move(r.store_id, r.product_id, "EXPIRY_WRITE_OFF", -int(r.qty), "BACKROOM", _at(r.write_off_date, 7),
             None, f"{r.reason}, batch {r.batch_no}", r.write_off_date, r.batch_no)  # fmt: skip

    groups: Any = snaps.sort_values("snapshot_date").groupby(["store_id", "product_id"], sort=False)
    for (store, product), g in groups:
        expected: int | None = None
        for day, closing in zip(g["snapshot_date"], g["closing_on_hand"], strict=True):
            delta = (
                int(rec_by_day.get((store, product, day), 0))
                - int(sold.get((store, product, day), 0))
                - int(wo_by_day.get((store, product, day), 0))
            )
            sale = int(sold.get((store, product, day), 0))
            move(store, product, "SALE", -sale, "SHELF", _at(day, 20), "BILL", "Daily POS sales", day)
            if expected is None:  # opening balance so that the first day closes at the POS figure
                move(store, product, "ADJUSTMENT", int(closing) - delta, "BACKROOM", _at(day, 0, 1), None,
                     "Opening balance (data import)", day)  # fmt: skip
            elif expected + delta != int(closing):
                adjustments += 1
                move(store, product, "ADJUSTMENT", int(closing) - (expected + delta), "BACKROOM", _at(day, 23),
                     "RECON", "POS stock count differs from the ledger", day)  # fmt: skip
            expected = int(closing)
    mov_cols = ["movement_id", "occurred_at", "business_date", "store_id", "product_id", "movement_type", "qty",
                "location", "reference_type", "reason"]  # fmt: skip
    n_moves = _copy(session, "inventory_movement", mov_cols, movements)

    # --- positions, batches -------------------------------------------------------------------------------------
    last = snaps[snaps["snapshot_date"] == through]
    incoming: dict[tuple[UUID, UUID], int] = defaultdict(int)
    for r in _rows(ds.open_orders):
        incoming[(r.store_id, r.product_id)] += int(r.qty)
    for start in range(0, len(last), 1000):
        chunk = last.iloc[start : start + 1000]
        rows = [
            {
                "store_id": r.store_id,
                "product_id": r.product_id,
                "shelf_qty": int(r.shelf_qty),
                "backroom_qty": int(r.backroom_qty),
                "incoming": incoming.get((r.store_id, r.product_id), 0),
            }
            for r in _rows(chunk)
        ]
        stmt = insert(InventoryPosition).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["store_id", "product_id"],
                set_={
                    "shelf_qty": stmt.excluded.shelf_qty,
                    "backroom_qty": stmt.excluded.backroom_qty,
                    "incoming": stmt.excluded.incoming,
                },
            )
        )
    _upsert(
        session, Batch, ds.batches, ["batch_id", "store_id", "product_id", "batch_no", "qty", "expiry_date"]
    )
    session.flush()
    return LoadReport(n_stores, n_products, n_bills, n_lines, n_snaps, n_moves, adjustments, through)
