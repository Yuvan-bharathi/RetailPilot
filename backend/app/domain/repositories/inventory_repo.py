"""Inventory repository: inventory position access, row locks, and daily snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models.inventory import InventoryDailySnapshot, InventoryPosition


class InventoryRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_position(self, store_id: UUID, product_id: UUID) -> InventoryPosition | None:
        stmt = select(InventoryPosition).where(
            InventoryPosition.store_id == store_id,
            InventoryPosition.product_id == product_id,
        )
        return self.session.scalars(stmt).one_or_none()

    def get_positions_for_update(
        self, store_id: UUID, product_ids: Sequence[UUID]
    ) -> dict[UUID, InventoryPosition]:
        """Fetch positions with a pessimistic row lock (FOR UPDATE)."""
        if not product_ids:
            return {}
        stmt = (
            select(InventoryPosition)
            .where(
                InventoryPosition.store_id == store_id,
                InventoryPosition.product_id.in_(product_ids),
            )
            .with_for_update()
        )
        positions = self.session.scalars(stmt).all()
        return {p.product_id: p for p in positions}

    def upsert_daily_snapshot(
        self, store_id: UUID, snapshot_date: date, rows: list[tuple[UUID, int, int, int]]
    ) -> int:
        """Upsert daily snapshots (product_id, shelf_qty, backroom_qty, closing_on_hand)."""
        if not rows:
            return 0
        data = [
            {
                "store_id": store_id,
                "product_id": pid,
                "snapshot_date": snapshot_date,
                "shelf_qty": shelf,
                "backroom_qty": backroom,
                "closing_on_hand": on_hand,
            }
            for pid, shelf, backroom, on_hand in rows
        ]
        stmt = insert(InventoryDailySnapshot).values(data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["store_id", "product_id", "snapshot_date"],
            set_={
                "shelf_qty": stmt.excluded.shelf_qty,
                "backroom_qty": stmt.excluded.backroom_qty,
                "closing_on_hand": stmt.excluded.closing_on_hand,
            },
        )
        self.session.execute(stmt)
        return len(rows)
