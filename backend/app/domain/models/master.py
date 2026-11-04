"""Master data (CD-1 "Master data"): stores, products, suppliers, terms, calendar."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Money, Timestamps, uuid_pk
from app.domain.models.enums import CalendarEventType, check_in


class Store(Timestamps, Base):
    __tablename__ = "store"

    store_id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    store_type: Mapped[str] = mapped_column(Text)
    location_context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    display_capacity: Mapped[int]


class Product(Timestamps, Base):
    __tablename__ = "product"
    __table_args__ = (
        # `q` search on name / SKU: trigram GIN indexes make ILIKE '%term%' indexable (D-38, pg_trgm)
        Index(
            "ix_product_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}
        ),
        Index("ix_product_sku_trgm", "sku", postgresql_using="gin", postgresql_ops={"sku": "gin_trgm_ops"}),
        CheckConstraint("pack_size >= 1", name="pack_size"),
        CheckConstraint("shelf_life_days IS NULL OR shelf_life_days >= 1", name="shelf_life_days"),
    )

    product_id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, index=True)
    brand: Mapped[str] = mapped_column(Text)
    cost_price: Mapped[Money]
    selling_price: Mapped[Money]
    pack_size: Mapped[int] = mapped_column(server_default="1")
    shelf_life_days: Mapped[int | None]  # null = not perishable


class Supplier(Timestamps, Base):
    __tablename__ = "supplier"

    supplier_id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    default_lead_time_days: Mapped[int]
    is_active: Mapped[bool] = mapped_column(server_default="true")


class StoreProduct(Timestamps, Base):
    """Per-store listing and replenishment parameters; the preferred supplier serves THAT store (rule 1, D-05)."""

    __tablename__ = "store_product"

    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.product_id"), primary_key=True, index=True
    )
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier.supplier_id"), index=True
    )
    min_display_qty: Mapped[int] = mapped_column(server_default="0")
    safety_stock_days: Mapped[int] = mapped_column(server_default="0")
    review_period_days: Mapped[int]
    abc_class: Mapped[str | None] = mapped_column(String(1))
    xyz_class: Mapped[str | None] = mapped_column(String(1))
    is_listed: Mapped[bool] = mapped_column(server_default="true")


class SupplierProduct(Timestamps, Base):
    __tablename__ = "supplier_product"
    __table_args__ = (
        CheckConstraint("moq >= 0", name="moq"),  # 0 = no minimum order quantity (D-47)
        CheckConstraint("order_pack_size >= 1", name="order_pack_size"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.supplier_id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.product_id"), primary_key=True, index=True
    )
    price: Mapped[Money]
    lead_time_days: Mapped[int]
    moq: Mapped[int] = mapped_column(server_default="1")
    order_pack_size: Mapped[int] = mapped_column(server_default="1")


class SupplierStoreTerms(Timestamps, Base):
    """Lead time and delivery charge of a supplier for one store (requirements §5.3)."""

    __tablename__ = "supplier_store_terms"

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.supplier_id"), primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True, index=True)
    lead_time_days: Mapped[int]
    delivery_charge: Mapped[Money]


class CalendarEvent(Timestamps, Base):
    __tablename__ = "calendar_event"
    __table_args__ = (CheckConstraint(check_in("event_type", CalendarEventType), name="event_type"),)

    event_id: Mapped[uuid.UUID] = uuid_pk()
    event_date: Mapped[date] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
