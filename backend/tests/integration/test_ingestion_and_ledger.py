"""Integration tests for InventoryLedgerService and DataIngestionService on PostgreSQL 16."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.domain.models.enums import MovementReference, MovementType, StockLocation
from app.domain.models.inventory import InventoryDailySnapshot, InventoryMovement, InventoryPosition
from app.domain.models.sales import SalesLine
from app.domain.schemas.ingestion import PosSource, RawBatchRow, RawBillLine, RawStockRow
from app.services.ingestion_service import DataIngestionService
from app.services.ledger_service import InventoryLedgerService
from tests.integration import factories as f

pytestmark = pytest.mark.integration

D = date(2026, 11, 3)
NOW = datetime(2026, 11, 3, 10, 0, 0, tzinfo=UTC)


class InMemoryPosSource(PosSource):
    def __init__(
        self,
        sales: list[RawBillLine] | None = None,
        snapshots: list[RawStockRow] | None = None,
        batches: list[RawBatchRow] | None = None,
    ) -> None:
        self.sales = sales or []
        self.snapshots = snapshots or []
        self.batches = batches or []

    def fetch_sales(self, store_id: UUID, day: date) -> list[RawBillLine]:
        return [s for s in self.sales if s.store_id == store_id and s.txn_date == day]

    def fetch_stock_snapshot(self, store_id: UUID, day: date) -> list[RawStockRow]:
        return [s for s in self.snapshots if s.store_id == store_id and s.snapshot_date == day]

    def fetch_batches(self, store_id: UUID) -> list[RawBatchRow]:
        return [b for b in self.batches if b.store_id == store_id]


def test_ledger_posts_movements_and_updates_position(db: Connection) -> None:
    session = Session(bind=db)
    store_id = f.store(db)
    product_id = f.product(db)

    ledger = InventoryLedgerService(session)

    # 1. Post a PO receipt of 50 units to SHELF
    receipt = InventoryMovement(
        movement_id=uuid.uuid4(),
        occurred_at=NOW,
        business_date=D,
        store_id=store_id,
        product_id=product_id,
        movement_type=MovementType.PO_RECEIPT,
        qty=50,
        location=StockLocation.SHELF,
        reference_type=MovementReference.PO,
    )
    ledger.post([receipt])

    pos = session.scalars(
        select(InventoryPosition).where(
            InventoryPosition.store_id == store_id,
            InventoryPosition.product_id == product_id,
        )
    ).one()
    assert pos.shelf_qty == 50
    assert pos.backroom_qty == 0
    assert pos.on_hand == 50

    # 2. Post a SALE of 5 units from SHELF
    sale = InventoryMovement(
        movement_id=uuid.uuid4(),
        occurred_at=NOW,
        business_date=D,
        store_id=store_id,
        product_id=product_id,
        movement_type=MovementType.SALE,
        qty=-5,
        location=StockLocation.SHELF,
        reference_type=MovementReference.BILL,
    )
    ledger.post([sale])

    session.refresh(pos)
    assert pos.shelf_qty == 45
    assert pos.on_hand == 45

    # 3. Assert movement was routed to the partition
    movements = session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.store_id == store_id,
            InventoryMovement.product_id == product_id,
        )
    ).all()
    assert len(movements) == 2


def test_ledger_reconciliation_posts_adjustment(db: Connection) -> None:
    session = Session(bind=db)
    store_id = f.store(db)
    product_id = f.product(db)

    ledger = InventoryLedgerService(session)

    # Initial position: 20 units
    init_mov = InventoryMovement(
        movement_id=uuid.uuid4(),
        occurred_at=NOW,
        business_date=D,
        store_id=store_id,
        product_id=product_id,
        movement_type=MovementType.PO_RECEIPT,
        qty=20,
        location=StockLocation.SHELF,
        reference_type=MovementReference.PO,
    )
    ledger.post([init_mov])

    # Physical count snapshot shows 17 units on shelf (discrepancy of -3)
    snapshot = [
        RawStockRow(
            store_id=store_id,
            product_id=product_id,
            snapshot_date=D,
            shelf_qty=17,
            backroom_qty=0,
            closing_on_hand=17,
        )
    ]

    adjustments = ledger.reconcile(store_id, snapshot)
    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.movement_type == MovementType.ADJUSTMENT
    assert adj.qty == -3
    assert adj.location == StockLocation.SHELF
    assert adj.reason == "RECON"

    # Verify updated position
    pos = session.scalars(
        select(InventoryPosition).where(
            InventoryPosition.store_id == store_id,
            InventoryPosition.product_id == product_id,
        )
    ).one()
    assert pos.shelf_qty == 17
    assert pos.on_hand == 17


def test_ingestion_service_loads_sales_and_reconciles(db: Connection) -> None:
    session = Session(bind=db)
    store_id = f.store(db)
    product_id = f.product(db)
    bill_id = uuid.uuid4()

    sales = [
        RawBillLine(
            bill_id=bill_id,
            line_no=1,
            txn_datetime=NOW,
            txn_date=D,
            store_id=store_id,
            product_id=product_id,
            qty=4,
            unit_price=Decimal("50.00"),
            discount=Decimal("0.00"),
        )
    ]
    snapshots = [
        RawStockRow(
            store_id=store_id,
            product_id=product_id,
            snapshot_date=D,
            shelf_qty=20,
            backroom_qty=10,
            closing_on_hand=30,
        )
    ]

    pos_source = InMemoryPosSource(sales=sales, snapshots=snapshots)
    ingestion = DataIngestionService(session, pos_source)

    report = ingestion.load_and_validate(D, [store_id])

    assert report.valid_rows == 1
    assert len(report.errors) == 0

    # Verify sales_line row exists
    lines = session.scalars(
        select(SalesLine).where(
            SalesLine.store_id == store_id,
            SalesLine.product_id == product_id,
        )
    ).all()
    assert len(lines) == 1
    assert lines[0].qty == 4

    # Verify daily snapshot was stored
    snaps = session.scalars(
        select(InventoryDailySnapshot).where(
            InventoryDailySnapshot.store_id == store_id,
            InventoryDailySnapshot.product_id == product_id,
        )
    ).all()
    assert len(snaps) == 1
    assert snaps[0].closing_on_hand == 30


def test_ingestion_detects_stale_skus(db: Connection) -> None:
    session = Session(bind=db)
    store_id = f.store(db)
    product_id = f.product(db)
    bill_id = uuid.uuid4()

    # Product sold 45 days ago
    old_date = D - date.resolution * 45
    old_time = NOW - date.resolution * 45

    sales = [
        RawBillLine(
            bill_id=bill_id,
            line_no=1,
            txn_datetime=old_time,
            txn_date=old_date,
            store_id=store_id,
            product_id=product_id,
            qty=2,
            unit_price=Decimal("100.00"),
            discount=Decimal("0.00"),
        )
    ]
    snapshots = [
        RawStockRow(
            store_id=store_id,
            product_id=product_id,
            snapshot_date=D,
            shelf_qty=10,
            backroom_qty=0,
            closing_on_hand=10,
        )
    ]

    pos_source = InMemoryPosSource(sales=sales, snapshots=snapshots)
    ingestion = DataIngestionService(session, pos_source)

    # Ingest old sales first
    ingestion.load_and_validate(old_date, [store_id])

    # Ingest today's run
    report = ingestion.load_and_validate(D, [store_id])

    # Should be flagged as stale because last sale > 30 days ago and stock > 0
    assert (store_id, product_id) in report.stale_skus
