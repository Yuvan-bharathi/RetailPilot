"""Sales repository: bill/line bulk ingestion and sale date queries."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.models.sales import SalesLine, SalesTransaction


class SalesRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert_bills(self, bills: list[SalesTransaction]) -> None:
        if not bills:
            return
        data = [
            {
                "bill_id": b.bill_id,
                "store_id": b.store_id,
                "txn_datetime": b.txn_datetime,
                "txn_date": b.txn_date,
                "total_amount": b.total_amount,
            }
            for b in bills
        ]
        stmt = insert(SalesTransaction).values(data)
        stmt = stmt.on_conflict_do_nothing(index_elements=["bill_id"])
        self.session.execute(stmt)

    def bulk_insert_lines(self, store_id: UUID, lines: list[SalesLine]) -> list[SalesLine]:
        """Bulk insert sales lines into the partitioned sales_line table (SD-02, D-41)."""
        if not lines:
            return []

        data = [
            {
                "bill_id": line.bill_id,
                "line_no": line.line_no,
                "txn_date": line.txn_date,
                "store_id": line.store_id,
                "product_id": line.product_id,
                "qty": line.qty,
                "unit_price": line.unit_price,
                "discount": line.discount,
                "is_return": line.is_return,
                "is_voided": line.is_voided,
                "is_promo_day": line.is_promo_day,
            }
            for line in lines
        ]

        stmt = insert(SalesLine).values(data)
        stmt = stmt.on_conflict_do_nothing(index_elements=["bill_id", "line_no", "txn_date"])
        self.session.execute(stmt)
        return lines

    def get_last_sale_dates(self, store_id: UUID) -> dict[UUID, date]:
        """Returns the most recent valid sale date for each product in the store (SD-02)."""
        stmt = (
            select(SalesLine.product_id, func.max(SalesLine.txn_date).label("last_sale"))
            .where(
                SalesLine.store_id == store_id,
                SalesLine.is_voided.is_(False),
                SalesLine.is_return.is_(False),
                SalesLine.qty > 0,
            )
            .group_by(SalesLine.product_id)
        )
        rows = self.session.execute(stmt).all()
        return {pid: last_sale for pid, last_sale in rows if last_sale is not None}
