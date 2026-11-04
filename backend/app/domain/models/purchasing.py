"""Purchase orders, lines and goods receipts (CD-2, spec §2, D-01, D-08, D-16)."""

import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Money, Timestamps, rel, uuid_pk
from app.domain.models.enums import ApprovalLevelRequired, LineStatus, POStatus, check_in


class PurchaseOrder(Timestamps, Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        # approval deadline job (SD-14): PENDING_L1 POs by deadline (D-38)
        Index(
            "ix_purchase_order_l1_deadline_pending",
            "l1_deadline",
            postgresql_where=text("status = 'PENDING_L1'"),
        ),
        Index("ix_purchase_order_status", "status"),
        CheckConstraint(check_in("status", POStatus), name="status"),
        CheckConstraint(check_in("required_level", ApprovalLevelRequired), name="required_level"),
    )

    po_id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.supplier_id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    total_value: Mapped[Money]
    required_level: Mapped[str] = mapped_column(Text, server_default=ApprovalLevelRequired.L1.value)
    parent_po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order.po_id"), index=True)
    l1_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=POStatus.DRAFT.value)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    explanation: Mapped[str | None] = mapped_column(Text)
    supplier_ref: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["POLine"]] = rel(back_populates="purchase_order", order_by="POLine.po_line_id")


class POLine(Timestamps, Base):
    __tablename__ = "po_line"
    __table_args__ = (
        # supervisor L1 queue: their store's PENDING lines (D-38)
        Index(
            "ix_po_line_store_pending",
            "store_id",
            "po_id",
            postgresql_where=text("line_status = 'PENDING'"),
        ),
        CheckConstraint(check_in("line_status", LineStatus), name="line_status"),
        CheckConstraint("qty >= 0", name="qty"),
        CheckConstraint("received_qty >= 0 AND short_closed_qty >= 0", name="received_qty"),
    )

    po_line_id: Mapped[uuid.UUID] = uuid_pk()
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_order.po_id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    qty: Mapped[int]
    unit_price: Mapped[Money]
    scheme_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("supplier_scheme.scheme_id"), index=True)
    source_rec_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.rec_id"), index=True)
    line_status: Mapped[str] = mapped_column(Text, server_default=LineStatus.PENDING.value)
    received_qty: Mapped[int] = mapped_column(server_default="0")
    short_closed_qty: Mapped[int] = mapped_column(server_default="0")

    purchase_order: Mapped[PurchaseOrder] = rel(back_populates="lines")


class GoodsReceipt(Timestamps, Base):
    __tablename__ = "goods_receipt"

    receipt_id: Mapped[uuid.UUID] = uuid_pk()
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_order.po_id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), index=True)
    received_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["GoodsReceiptLine"]] = rel(back_populates="receipt")


class GoodsReceiptLine(Timestamps, Base):
    __tablename__ = "goods_receipt_line"
    __table_args__ = (CheckConstraint("qty > 0", name="qty"),)

    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipt.receipt_id"), primary_key=True)
    po_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("po_line.po_line_id"), primary_key=True, index=True
    )
    qty: Mapped[int]
    batch_no: Mapped[str | None] = mapped_column(Text)
    expiry_date: Mapped[date | None]

    receipt: Mapped[GoodsReceipt] = rel(back_populates="lines")
