"""Batch repository: FEFO batch tracking and bulk upserts (SD-02, SD-08)."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models.inventory import Batch


class BatchRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_expiring(self, store_ids: list[UUID], as_of_date: date, within_days: int = 14) -> list[Batch]:
        """Fetch held batches expiring within window (D-38, SD-08)."""
        if not store_ids:
            return []
        cutoff = as_of_date + timedelta(days=within_days)
        stmt = (
            select(Batch)
            .where(
                Batch.store_id.in_(store_ids),
                Batch.qty > 0,
                Batch.expiry_date >= as_of_date,
                Batch.expiry_date <= cutoff,
            )
            .order_by(Batch.store_id, Batch.product_id, Batch.expiry_date.asc())
        )
        return list(self.session.scalars(stmt).all())

    def bulk_upsert(self, store_id: UUID, batches: list[Batch]) -> int:
        if not batches:
            return 0
        data = [
            {
                "batch_id": b.batch_id,
                "store_id": store_id,
                "product_id": b.product_id,
                "batch_no": b.batch_no,
                "qty": b.qty,
                "received_date": b.received_date,
                "expiry_date": b.expiry_date,
            }
            for b in batches
        ]
        stmt = insert(Batch).values(data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["batch_id"],
            set_={
                "qty": stmt.excluded.qty,
                "expiry_date": stmt.excluded.expiry_date,
                "received_date": stmt.excluded.received_date,
            },
        )
        self.session.execute(stmt)
        return len(batches)
