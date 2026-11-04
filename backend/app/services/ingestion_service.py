"""Data Ingestion Service (SD-02, spec §8, decision D-41).

Loads, validates, and ingests POS sales, stock snapshots, and batch records.
All stock deductions from sales and snapshot reconciliations flow strictly through
the InventoryLedgerService.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.enums import MovementReference, MovementType, StockLocation
from app.domain.models.inventory import Batch, InventoryMovement, InventoryPosition
from app.domain.models.master import Product
from app.domain.models.sales import SalesLine, SalesTransaction
from app.domain.models.transfers import BusinessRule
from app.domain.repositories.batch_repo import BatchRepo
from app.domain.repositories.inventory_repo import InventoryRepo
from app.domain.repositories.sales_repo import SalesRepo
from app.domain.schemas.ingestion import PosSource, RawBillLine, RawStockRow, ValidationReport
from app.services.ledger_service import InventoryLedgerService


class DataIngestionService:
    def __init__(self, session: Session, pos_source: PosSource) -> None:
        self.session = session
        self.pos_source = pos_source
        self.ledger = InventoryLedgerService(session)
        self.sales_repo = SalesRepo(session)
        self.inventory_repo = InventoryRepo(session)
        self.batch_repo = BatchRepo(session)

    def _get_stale_days(self) -> int:
        rule = self.session.scalars(
            select(BusinessRule).where(
                BusinessRule.rule_key == "stale_days", BusinessRule.scope_store_id.is_(None)
            )
        ).one_or_none()
        if rule and rule.value is not None:
            try:
                return int(rule.value)
            except (ValueError, TypeError):
                pass
        return 30

    def validate_sales(
        self, rows: Sequence[RawBillLine], run_date: date, known_product_ids: set[UUID]
    ) -> tuple[list[SalesLine], list[SalesTransaction], list[str]]:
        valid_lines: list[SalesLine] = []
        bills_map: dict[UUID, SalesTransaction] = {}
        errors: list[str] = []
        seen_keys: set[tuple[UUID, int]] = set()

        for r in rows:
            key = (r.bill_id, r.line_no)
            if key in seen_keys:
                errors.append(f"duplicate line: bill {r.bill_id} line {r.line_no}")
                continue
            seen_keys.add(key)

            if r.product_id not in known_product_ids:
                errors.append(f"unknown product_id: {r.product_id}")
                continue

            if r.qty <= 0:
                errors.append(f"invalid qty {r.qty} on bill {r.bill_id} line {r.line_no}")
                continue

            if r.unit_price < Decimal("0"):
                errors.append(f"negative price on bill {r.bill_id} line {r.line_no}")
                continue

            if r.discount > (r.unit_price * r.qty):
                errors.append(f"discount exceeds total on bill {r.bill_id} line {r.line_no}")
                continue

            if r.txn_date != run_date:
                errors.append(f"txn_date {r.txn_date} mismatch with run_date {run_date}")
                continue

            # Valid bill line
            line = SalesLine(
                bill_id=r.bill_id,
                line_no=r.line_no,
                txn_date=r.txn_date,
                store_id=r.store_id,
                product_id=r.product_id,
                qty=r.qty,
                unit_price=r.unit_price,
                discount=r.discount,
                is_return=r.is_return,
                is_voided=r.is_voided,
                is_promo_day=r.is_promo_day,
            )
            valid_lines.append(line)

            # Bill header aggregation
            line_total = (r.unit_price * r.qty) - r.discount
            if r.bill_id not in bills_map:
                bills_map[r.bill_id] = SalesTransaction(
                    bill_id=r.bill_id,
                    store_id=r.store_id,
                    txn_datetime=r.txn_datetime,
                    txn_date=r.txn_date,
                    total_amount=line_total,
                )
            else:
                bills_map[r.bill_id].total_amount += line_total

        return valid_lines, list(bills_map.values()), errors

    def validate_stock(
        self, rows: Sequence[RawStockRow], known_product_ids: set[UUID]
    ) -> tuple[list[RawStockRow], list[str]]:
        valid_rows: list[RawStockRow] = []
        errors: list[str] = []

        for r in rows:
            if r.product_id not in known_product_ids:
                errors.append(f"unknown product in stock snapshot: {r.product_id}")
                continue
            if r.shelf_qty < 0 or r.backroom_qty < 0:
                errors.append(f"negative stock in snapshot for product: {r.product_id}")
                continue
            valid_rows.append(r)

        return valid_rows, errors

    def load_and_validate(self, run_date: date, store_ids: list[UUID]) -> ValidationReport:
        """Run daily ingestion and validation for given stores on run_date (SD-02)."""
        report = ValidationReport()
        known_product_ids = set(self.session.scalars(select(Product.product_id)).all())
        stale_days = self._get_stale_days()

        for store_id in store_ids:
            # 1. Fetch raw rows
            raw_lines = self.pos_source.fetch_sales(store_id, run_date)
            raw_stock = self.pos_source.fetch_stock_snapshot(store_id, run_date)
            raw_batches = self.pos_source.fetch_batches(store_id)

            # 2. Validate and insert sales
            valid_lines, valid_bills, line_errors = self.validate_sales(
                raw_lines, run_date, known_product_ids
            )
            report.errors.extend(line_errors)

            self.sales_repo.bulk_insert_bills(valid_bills)
            inserted_lines = self.sales_repo.bulk_insert_lines(store_id, valid_lines)
            report.valid_rows += len(inserted_lines)

            # 3. Post sale deductions through the ledger
            sale_movements: list[InventoryMovement] = []
            for line in inserted_lines:
                if not line.is_voided and not line.is_return:
                    sale_movements.append(
                        InventoryMovement(
                            movement_id=uuid.uuid4(),
                            occurred_at=datetime.combine(line.txn_date, datetime.min.time()),
                            business_date=line.txn_date,
                            store_id=store_id,
                            product_id=line.product_id,
                            movement_type=MovementType.SALE,
                            qty=-line.qty,
                            location=StockLocation.SHELF,
                            reference_type=MovementReference.BILL,
                            reference_id=line.bill_id,
                        )
                    )
            self.ledger.post(sale_movements)

            # 4. Reconcile stock snapshot
            if not raw_stock:
                report.errors.append(f"no snapshot: {store_id}")
            else:
                valid_stock, stock_errors = self.validate_stock(raw_stock, known_product_ids)
                report.errors.extend(stock_errors)
                self.ledger.reconcile(store_id, valid_stock)

                # Persist daily snapshot
                snapshot_rows = [
                    (s.product_id, s.shelf_qty, s.backroom_qty, s.closing_on_hand)
                    for s in valid_stock
                ]
                self.inventory_repo.upsert_daily_snapshot(store_id, run_date, snapshot_rows)

            # 5. Upsert batches
            if raw_batches:
                batch_models = [
                    Batch(
                        batch_id=b.batch_id,
                        store_id=store_id,
                        product_id=b.product_id,
                        batch_no=b.batch_no,
                        qty=b.qty,
                        received_date=b.received_date,
                        expiry_date=b.expiry_date,
                    )
                    for b in raw_batches
                    if b.product_id in known_product_ids
                ]
                self.batch_repo.bulk_upsert(store_id, batch_models)

            # 6. Check for stale SKUs
            last_sales = self.sales_repo.get_last_sale_dates(store_id)
            pos_stmt = select(InventoryPosition).where(
                InventoryPosition.store_id == store_id,
                (InventoryPosition.shelf_qty + InventoryPosition.backroom_qty) > 0,
            )
            positions_with_stock = self.session.scalars(pos_stmt).all()
            for pos in positions_with_stock:
                last_sale = last_sales.get(pos.product_id)
                if last_sale is not None and (run_date - last_sale).days > stale_days:
                    report.stale_skus.append((store_id, pos.product_id))

        self.session.flush()
        return report

    def backfill(
        self, start: date, end: date, store_ids: list[UUID]
    ) -> ValidationReport:
        """Backfill historical sales and stock across a date range [start, end] (SD-02 line 57)."""
        combined = ValidationReport()
        current = start
        while current <= end:
            rep = self.load_and_validate(current, store_ids)
            combined.valid_rows += rep.valid_rows
            combined.errors.extend(rep.errors)
            # Stale skus are evaluated at the final day
            if current == end:
                combined.stale_skus = rep.stale_skus
            current += timedelta(days=1)
        return combined
