"""Stock (CD-1 "Sales & inventory", spec §3).

Stock changes ONLY through `inventory_movement` (CLAUDE.md rule 8); `inventory_position` is the maintained
projection plus the commitments `incoming` / `reserved` (spec §2, D-03). `inventory_movement` is range-partitioned
by month on `occurred_at` (when the stock moved; D-37); `created_at` is insert/audit time only.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Timestamps, uuid_pk
from app.domain.models.enums import MovementReference, MovementType, StockLocation, check_in


class InventoryPosition(Timestamps, Base):
    __tablename__ = "inventory_position"

    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.product_id"), primary_key=True, index=True
    )
    shelf_qty: Mapped[int] = mapped_column(server_default="0")
    backroom_qty: Mapped[int] = mapped_column(server_default="0")
    reserved: Mapped[int] = mapped_column(server_default="0")  # accepted outgoing transfers
    incoming: Mapped[int] = mapped_column(
        server_default="0"
    )  # accepted incoming transfers + approved PO lines
    in_transit_out: Mapped[int] = mapped_column(server_default="0")

    @property
    def on_hand(self) -> int:
        return self.shelf_qty + self.backroom_qty

    @property
    def available(self) -> int:
        return self.on_hand + self.incoming - self.reserved


class InventoryDailySnapshot(Timestamps, Base):
    """Closing stock per store-product-day from the POS (D-09); stockout day = closing_on_hand = 0."""

    __tablename__ = "inventory_daily_snapshot"
    __table_args__ = (Index("ix_inventory_daily_snapshot_store_day", "store_id", "snapshot_date"),)

    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.product_id"), primary_key=True, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(primary_key=True)
    shelf_qty: Mapped[int]
    backroom_qty: Mapped[int]
    closing_on_hand: Mapped[int]


class Batch(Timestamps, Base):
    __tablename__ = "batch"
    __table_args__ = (
        # expiring-soon tab and freshness scan: only batches that still hold stock (D-38)
        Index("ix_batch_store_expiry_held", "store_id", "expiry_date", postgresql_where=text("qty > 0")),
        Index("ix_batch_store_product", "store_id", "product_id"),
        CheckConstraint("qty >= 0", name="qty"),
    )

    batch_id: Mapped[uuid.UUID] = uuid_pk()
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    batch_no: Mapped[str] = mapped_column(Text)
    qty: Mapped[int]
    received_date: Mapped[date | None]
    expiry_date: Mapped[date]


class InventoryMovement(Timestamps, Base):
    """The stock ledger. Indexes are declared on this partitioned parent, so every partition inherits them."""

    __tablename__ = "inventory_movement"
    __table_args__ = (
        Index("ix_inventory_movement_batch_id", "batch_id", postgresql_where=text("batch_id IS NOT NULL")),
        Index("ix_inventory_movement_user_id", "user_id", postgresql_where=text("user_id IS NOT NULL")),
        CheckConstraint(check_in("movement_type", MovementType), name="movement_type"),
        CheckConstraint(check_in("location", StockLocation), name="location"),
        CheckConstraint(
            f"reference_type IS NULL OR {check_in('reference_type', MovementReference)}",
            name="reference_type",
        ),
        CheckConstraint("qty <> 0", name="qty"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    movement_id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    business_date: Mapped[date]
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batch.batch_id"))
    movement_type: Mapped[str] = mapped_column(Text)
    qty: Mapped[int]  # signed: + in, − out
    location: Mapped[str] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(Text)
    reference_id: Mapped[uuid.UUID | None]
    reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.user_id"))


# Movements tab, keyset paging newest first (D-37), and per-product ledger history. Declared on the partitioned
# parent: PostgreSQL creates a matching index on every partition, including partitions created later.
Index(
    "ix_inventory_movement_store_time",
    InventoryMovement.store_id,
    InventoryMovement.occurred_at.desc(),
    InventoryMovement.movement_id.desc(),
)
Index(
    "ix_inventory_movement_store_product_time",
    InventoryMovement.store_id,
    InventoryMovement.product_id,
    InventoryMovement.occurred_at.desc(),
)
