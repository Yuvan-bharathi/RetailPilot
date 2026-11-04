"""Later-extension tables (CD-1 `SupplierScheme`, CD-2 digital twin). Created now; no logic yet (PROMPTS.md Phase 2)."""

import uuid
from datetime import date

from sqlalchemy import Double, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Timestamps, uuid_pk


class SupplierScheme(Timestamps, Base):
    __tablename__ = "supplier_scheme"

    scheme_id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.supplier_id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    slab_qty: Mapped[int]
    free_qty: Mapped[int]
    valid_from: Mapped[date]
    valid_to: Mapped[date]


class StoreLayout(Timestamps, Base):
    __tablename__ = "store_layout"

    layout_id: Mapped[uuid.UUID] = uuid_pk()
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), index=True)
    width_m: Mapped[float] = mapped_column(Double)
    depth_m: Mapped[float] = mapped_column(Double)
    version: Mapped[int] = mapped_column(server_default="1")


class ShelfLocation(Timestamps, Base):
    __tablename__ = "shelf_location"

    shelf_id: Mapped[uuid.UUID] = uuid_pk()
    layout_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store_layout.layout_id"), index=True)
    aisle: Mapped[str] = mapped_column(Text)
    x: Mapped[float] = mapped_column(Double)
    y: Mapped[float] = mapped_column(Double)
    z: Mapped[float] = mapped_column(Double)
    rotation: Mapped[float] = mapped_column(Double, server_default="0")
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.product_id"), index=True)
    facings: Mapped[int] = mapped_column(server_default="1")
