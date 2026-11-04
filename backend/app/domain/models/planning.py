"""Planning outputs written by the nightly run (CD-1). Every output references the AgentRun that produced it."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Computed, Double, ForeignKey, Index, Numeric, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import MONEY, Base, Money, Timestamps, uuid_pk
from app.domain.models.enums import (
    AssociationRuleType,
    Confidence,
    ForecastMethod,
    NeedReason,
    NeedSource,
    Priority,
    RecStatus,
    RecType,
    check_in,
)


class Forecast(Timestamps, Base):
    __tablename__ = "forecast"
    __table_args__ = (
        Index("ix_forecast_store_product", "store_id", "product_id"),
        CheckConstraint(check_in("method", ForecastMethod), name="method"),
        CheckConstraint(check_in("confidence", Confidence), name="confidence"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.product_id"), primary_key=True, index=True
    )
    horizon_days: Mapped[int]
    daily_demand: Mapped[float] = mapped_column(Double)
    method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)


class AssociationRule(Timestamps, Base):
    __tablename__ = "association_rule"
    __table_args__ = (
        Index("ix_association_rule_store_antecedent", "store_id", "antecedent_id"),
        CheckConstraint(check_in("rule_type", AssociationRuleType), name="rule_type"),
    )

    rule_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"))
    antecedent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    consequent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    support: Mapped[float] = mapped_column(Double)
    confidence: Mapped[float] = mapped_column(Double)
    lift: Mapped[float] = mapped_column(Double)
    rule_type: Mapped[str] = mapped_column(Text)


class Recommendation(Timestamps, Base):
    __tablename__ = "recommendation"
    __table_args__ = (
        # recommendations inbox: PENDING only, high priority first, oldest first (D-38)
        Index(
            "ix_recommendation_inbox_pending",
            "store_id",
            "priority_rank",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_recommendation_store_status", "store_id", "status"),
        CheckConstraint(check_in("rec_type", RecType), name="rec_type"),
        CheckConstraint(check_in("status", RecStatus), name="status"),
        CheckConstraint(check_in("priority", Priority), name="priority"),
        CheckConstraint("qty >= 0", name="qty"),
    )

    rec_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    rec_type: Mapped[str] = mapped_column(Text)
    qty: Mapped[int]
    priority: Mapped[str] = mapped_column(Text, server_default=Priority.NORMAL.value)
    # rank sort (spec §5: HIGH before NORMAL) as an indexable column, maintained by PostgreSQL
    priority_rank: Mapped[int] = mapped_column(
        SmallInteger, Computed("CASE priority WHEN 'HIGH' THEN 0 ELSE 1 END", persisted=True)
    )
    reason: Mapped[str | None] = mapped_column(Text)
    lost_sales_value: Mapped[Decimal | None] = mapped_column(MONEY)  # lost revenue
    lost_profit: Mapped[Decimal | None] = mapped_column(MONEY)
    explanation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)  # validated against the evidence union (D-34)
    status: Mapped[str] = mapped_column(Text, server_default=RecStatus.PENDING.value)


class ReplenishmentNeed(Timestamps, Base):
    __tablename__ = "replenishment_need"
    __table_args__ = (
        Index("ix_replenishment_need_run_store", "run_id", "store_id"),
        CheckConstraint(check_in("source", NeedSource), name="source"),
        CheckConstraint(check_in("reason", NeedReason), name="reason"),
        CheckConstraint(check_in("priority", Priority), name="priority"),
    )

    need_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"))
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.product_id"), index=True)
    qty: Mapped[int]
    source: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    linked_product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.product_id"), index=True)
    lift: Mapped[float | None] = mapped_column(Double)
    rec_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendation.rec_id"), index=True)
    required_by: Mapped[date]


class KpiSnapshot(Timestamps, Base):
    __tablename__ = "kpi_snapshot"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True, index=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    # product_id, or the nil UUID for store-level KPIs (D-06) — deliberately not a foreign key
    product_key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class LostSalesEstimate(Timestamps, Base):
    __tablename__ = "lost_sales_estimate"
    __table_args__ = (CheckConstraint(check_in("confidence", Confidence), name="confidence"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store.store_id"), primary_key=True, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.product_id"), primary_key=True, index=True
    )
    lost_units: Mapped[float] = mapped_column(Double)
    lost_revenue: Mapped[Money]
    lost_profit: Mapped[Money]
    confidence: Mapped[str] = mapped_column(Text)
