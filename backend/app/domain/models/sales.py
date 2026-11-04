"""POS sales (CD-1 "Sales & inventory"). `sales_line` is range-partitioned by month on `txn_date` (D-06, D-35)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import MONEY, Base, Money, Timestamps, uuid_pk


class SalesTransaction(Timestamps, Base):
    """One POS bill. `txn_date` is the store's IST business day of `txn_datetime` (D-43)."""

    __tablename__ = "sales_transaction"
    __table_args__ = (Index("ix_sales_transaction_store_day", "store_id", "txn_date"),)

    bill_id: Mapped[uuid.UUID] = uuid_pk()
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"))
    txn_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    txn_date: Mapped[date]
    total_amount: Mapped[Money]


class SalesLine(Timestamps, Base):
    """A bill line. Partitioned by month on `txn_date`; PK includes the partition key, a line is identified by
    `(bill_id, line_no)`. Returns, voided lines and promotion days are flagged (SD-05 `clean_bills`, D-43).

    Indexes are declared on this parent table, so every monthly partition (including ones created later by the
    partition job) inherits them (D-38).
    """

    __tablename__ = "sales_line"
    __table_args__ = (
        Index("ix_sales_line_store_product_day", "store_id", "product_id", "txn_date"),
        CheckConstraint("qty > 0", name="qty"),
        {"postgresql_partition_by": "RANGE (txn_date)"},
    )

    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_transaction.bill_id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(primary_key=True)
    txn_date: Mapped[date] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    qty: Mapped[int]
    unit_price: Mapped[Money]
    discount: Mapped[Decimal] = mapped_column(MONEY, server_default="0")  # ₹ off the whole line
    is_return: Mapped[bool] = mapped_column(server_default="false")
    is_voided: Mapped[bool] = mapped_column(server_default="false")
    is_promo_day: Mapped[bool] = mapped_column(server_default="false")
