"""Agent runs, tool calls, evidence and LLM usage (CD-2 "Observability", SD-01, SD-02)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Timestamps, rel, uuid_pk
from app.domain.models.enums import AgentRunStatus, ToolCallStatus, check_in

NIGHTLY_AGENT = "nightly"


class AgentRun(Timestamps, Base):
    __tablename__ = "agent_run"
    __table_args__ = (
        # Idempotency guard (SD-01, D-35): at most one live or completed nightly run per date.
        # A FAILED run does not count, so the date can be re-run after a failure.
        Index(
            "uq_agent_run_nightly_run_date",
            "run_date",
            unique=True,
            postgresql_where=text(
                f"agent_name = '{NIGHTLY_AGENT}' AND status IN ('RUNNING', 'SUCCESS', 'PARTIAL')"
            ),
        ),
        # GET /runs/latest and the monitoring list
        Index("ix_agent_run_agent_started", "agent_name", "started_at"),
        CheckConstraint(check_in("status", AgentRunStatus), name="status"),
    )

    run_id: Mapped[uuid.UUID] = uuid_pk()
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    agent_name: Mapped[str] = mapped_column(Text)
    run_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(Text, server_default=AgentRunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    output_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    step_count: Mapped[int] = mapped_column(server_default="0")

    tool_calls: Mapped[list["ToolCall"]] = rel(back_populates="run")


class ToolCall(Timestamps, Base):
    __tablename__ = "tool_call"
    __table_args__ = (CheckConstraint(check_in("status", ToolCallStatus), name="status"),)

    call_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    tool_name: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    result_summary: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int]
    retries: Mapped[int] = mapped_column(server_default="0")
    status: Mapped[str] = mapped_column(Text)

    run: Mapped[AgentRun] = rel(back_populates="tool_calls")


class DecisionEvidence(Timestamps, Base):
    __tablename__ = "decision_evidence"

    evidence_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    rec_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendation.rec_id"), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation_result: Mapped[str] = mapped_column(Text)


class LLMUsage(Timestamps, Base):
    __tablename__ = "llm_usage"

    usage_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    # provider cost estimate (USD); fractions of a cent, so not the 2-decimal ₹ money type
    est_cost: Mapped[Decimal] = mapped_column(Numeric(14, 6))
