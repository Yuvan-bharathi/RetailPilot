"""Transfers between own stores, routes, approvals and business rules (CD-2, spec §2, D-03, D-06, D-15)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import MONEY, Base, Money, Timestamps, uuid_pk
from app.domain.models.enums import (
    ACTIVE_TRANSFER_STATUSES,
    ApprovalDecision,
    ApprovalEntity,
    ApprovalLevel,
    TransferStatus,
    check_in,
    sql_in,
)

_ACTIVE = text(f"status IN ({sql_in(ACTIVE_TRANSFER_STATUSES)})")


class TransferRoute(Timestamps, Base):
    __tablename__ = "transfer_route"
    __table_args__ = (CheckConstraint("from_store_id <> to_store_id", name="distinct_stores"),)

    from_store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True)
    to_store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True, index=True)
    fixed_cost: Mapped[Money]
    per_unit_cost: Mapped[Money]
    handling_cost_per_unit: Mapped[Money]
    transit_days: Mapped[int]


class TransferOrder(Timestamps, Base):
    __tablename__ = "transfer_order"
    __table_args__ = (
        # donor / destination views of transfers still in flight (D-38)
        Index("ix_transfer_order_from_active", "from_store_id", postgresql_where=_ACTIVE),
        Index("ix_transfer_order_to_active", "to_store_id", postgresql_where=_ACTIVE),
        CheckConstraint(check_in("status", TransferStatus), name="status"),
        CheckConstraint("from_store_id <> to_store_id", name="distinct_stores"),
        CheckConstraint("qty > 0", name="qty"),
    )

    transfer_id: Mapped[uuid.UUID] = uuid_pk()
    from_store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), index=True)
    to_store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batch.batch_id"), index=True)
    qty: Mapped[int]
    transfer_cost: Mapped[Money]
    transit_days: Mapped[int]
    is_expiry_aware: Mapped[bool] = mapped_column(server_default="false")
    source_rec_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.rec_id"), index=True)
    status: Mapped[str] = mapped_column(Text, server_default=TransferStatus.PROPOSED.value)
    dest_accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    donor_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_reason: Mapped[str | None] = mapped_column(Text)
    # discrepancy on receipt (D-06): no extra movement, the loss is recorded here
    expected_qty: Mapped[int | None]
    received_qty: Mapped[int | None]
    loss_value: Mapped[Decimal | None] = mapped_column(MONEY)


class Approval(Timestamps, Base):
    """One decision on a PO (L1 per store / L2) or a transfer (DEST / DONOR). `entity_id` is polymorphic."""

    __tablename__ = "approval"
    __table_args__ = (
        Index("ix_approval_entity", "entity_type", "entity_id"),
        CheckConstraint(check_in("entity_type", ApprovalEntity), name="entity_type"),
        CheckConstraint(check_in("level", ApprovalLevel), name="level"),
        CheckConstraint(check_in("decision", ApprovalDecision), name="decision"),
    )

    approval_id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID]
    level: Mapped[str] = mapped_column(Text)
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("store.store_id"), index=True)
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BusinessRule(Timestamps, Base):
    """Business parameters (spec §9). One global row per key (scope_store_id NULL) and at most one override per
    store: UNIQUE NULLS NOT DISTINCT (rule_key, scope_store_id) (D-35, PostgreSQL 15+)."""

    __tablename__ = "business_rule"
    __table_args__ = (
        Index(
            "uq_business_rule_key_scope",
            "rule_key",
            "scope_store_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    rule_id: Mapped[uuid.UUID] = uuid_pk()
    rule_key: Mapped[str] = mapped_column(Text)
    value: Mapped[Any] = mapped_column(JSONB)
    scope_store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("store.store_id"), index=True)
