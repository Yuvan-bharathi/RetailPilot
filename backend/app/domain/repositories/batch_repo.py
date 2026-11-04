"""Batch repository: FEFO batch tracking and bulk upserts (SD-02, SD-08)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models.inventory import Batch


class BatchRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

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
