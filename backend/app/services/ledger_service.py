"""Inventory Ledger Service (CLAUDE.md rule 8, SD-02, SD-12, spec §8).

Stock mutations execute strictly through this service: every change creates an immutable `inventory_movement`
row and atomically updates the projected `inventory_position`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.enums import MovementReference, MovementType, StockLocation
from app.domain.models.inventory import Batch, InventoryMovement, InventoryPosition
from app.domain.schemas.ingestion import RawStockRow


class InventoryLedgerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def post(self, movements: list[InventoryMovement]) -> None:
        """Post a batch of stock movements, updating inventory positions with row locking."""
        if not movements:
            return

        # 1. Group movements by (store_id, product_id)
        store_products: dict[tuple[UUID, UUID], list[InventoryMovement]] = defaultdict(list)
        batch_ids: set[UUID] = set()
        for m in movements:
            store_products[(m.store_id, m.product_id)].append(m)
            if m.batch_id is not None:
                batch_ids.add(m.batch_id)

        # 2. Lock and load all affected positions
        for (store_id, product_id), group in store_products.items():
            stmt = (
                select(InventoryPosition)
                .where(
                    InventoryPosition.store_id == store_id,
                    InventoryPosition.product_id == product_id,
                )
                .with_for_update()
            )
            pos = self.session.scalars(stmt).one_or_none()
            if pos is None:
                pos = InventoryPosition(
                    store_id=store_id,
                    product_id=product_id,
                    shelf_qty=0,
                    backroom_qty=0,
                    reserved=0,
                    incoming=0,
                    in_transit_out=0,
                )
                self.session.add(pos)

            # 3. Apply deltas to position
            for m in group:
                if m.location == StockLocation.SHELF:
                    pos.shelf_qty += m.qty
                elif m.location == StockLocation.BACKROOM:
                    pos.backroom_qty += m.qty

                # Handle commitment adjustments on execution
                if m.movement_type == MovementType.TRANSFER_OUT:
                    # Released from reserved into dispatch
                    pos.reserved = max(0, pos.reserved - abs(m.qty))
                elif m.movement_type == MovementType.TRANSFER_IN:
                    # Arrived at destination; clear expected incoming
                    pos.incoming = max(0, pos.incoming - abs(m.qty))
                elif m.movement_type == MovementType.PO_RECEIPT:
                    # Received from supplier; clear incoming
                    pos.incoming = max(0, pos.incoming - abs(m.qty))

                self.session.add(m)

        # 4. Apply batch updates if any batch movements exist
        if batch_ids:
            batches = {
                b.batch_id: b
                for b in self.session.scalars(
                    select(Batch).where(Batch.batch_id.in_(batch_ids)).with_for_update()
                ).all()
            }
            for m in movements:
                if m.batch_id and m.batch_id in batches:
                    b = batches[m.batch_id]
                    b.qty = max(0, b.qty + m.qty)

        self.session.flush()

    def reconcile(
        self, store_id: UUID, snapshot: Sequence[RawStockRow]
    ) -> list[InventoryMovement]:
        """Reconcile physical stock counts against ledger positions (SD-02 lines 34-40).

        For any discrepancy between snapshot counts and maintained positions, posts an
        ADJUSTMENT movement with reason="RECON".
        """
        if not snapshot:
            return []

        now = datetime.now(UTC)
        adjustments: list[InventoryMovement] = []

        product_ids = [row.product_id for row in snapshot]
        stmt = (
            select(InventoryPosition)
            .where(
                InventoryPosition.store_id == store_id,
                InventoryPosition.product_id.in_(product_ids),
            )
            .with_for_update()
        )
        existing_positions = {p.product_id: p for p in self.session.scalars(stmt).all()}

        for row in snapshot:
            pos = existing_positions.get(row.product_id)
            current_shelf = pos.shelf_qty if pos else 0
            current_backroom = pos.backroom_qty if pos else 0

            # Shelf difference
            shelf_diff = row.shelf_qty - current_shelf
            if shelf_diff != 0:
                adjustments.append(
                    InventoryMovement(
                        movement_id=uuid.uuid4(),
                        occurred_at=now,
                        business_date=row.snapshot_date,
                        store_id=store_id,
                        product_id=row.product_id,
                        movement_type=MovementType.ADJUSTMENT,
                        qty=shelf_diff,
                        location=StockLocation.SHELF,
                        reference_type=MovementReference.RECON,
                        reason="RECON",
                    )
                )

            # Backroom difference
            backroom_diff = row.backroom_qty - current_backroom
            if backroom_diff != 0:
                adjustments.append(
                    InventoryMovement(
                        movement_id=uuid.uuid4(),
                        occurred_at=now,
                        business_date=row.snapshot_date,
                        store_id=store_id,
                        product_id=row.product_id,
                        movement_type=MovementType.ADJUSTMENT,
                        qty=backroom_diff,
                        location=StockLocation.BACKROOM,
                        reference_type=MovementReference.RECON,
                        reason="RECON",
                    )
                )

        if adjustments:
            self.post(adjustments)

        return adjustments

