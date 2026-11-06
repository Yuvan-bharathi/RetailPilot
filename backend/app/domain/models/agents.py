"""Agent console and Objective III agent layer (docs/08, docs/09, D-50).

- `agent_definition`: the registry (seeded from `app.agents.registry`; new agents are added by registering them).
- `agent_config`: append-only, versioned on/off history (who, when, old → new, reason). The row with the highest
  `config_version` per agent is the current value; `agent_key` NULL is the global "All LLM agents" switch.
- `agent_decision`: one row per decision any agent took, with its evidence link and the human outcome.
- `agent_preview_output`: outputs of a DRY RUN trigger; never read by the inbox, POs, transfers, dashboards or cache.
- `agent_draft`: proposals of the Replenishment Action / Data Quality agents. A draft is never an approval: a human
  decides it through the existing recommendation / PO / transfer workflow.
- `recommendation_review`: the Recommendation Reviewer's verdict per recommendation ("Not reviewed" when absent).
- `policy_document`: SOP / policy sections (data/policies/*.md) for retrieval with PostgreSQL full-text search.
- `agent_eval_result`: evaluation-harness results per agent (tests/agent_evals, docs/notes/agent-eval-report.md).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Timestamps, uuid_pk
from app.domain.models.enums import (
    AgentGroup,
    AgentKind,
    AgentPattern,
    DecisionOutcome,
    DraftStatus,
    ReviewVerdict,
    RunMode,
    check_in,
)


class AgentDefinition(Timestamps, Base):
    __tablename__ = "agent_definition"
    __table_args__ = (
        CheckConstraint(check_in("agent_group", AgentGroup), name="agent_group"),
        CheckConstraint(check_in("kind", AgentKind), name="kind"),
        CheckConstraint(check_in("pattern", AgentPattern), name="pattern"),
    )

    agent_key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    agent_group: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    pattern: Mapped[str] = mapped_column(Text)
    critical: Mapped[bool] = mapped_column(server_default=text("false"))
    depends_on: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    card_path: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(server_default="0")


class AgentConfig(Timestamps, Base):
    __tablename__ = "agent_config"
    __table_args__ = (Index("ix_agent_config_agent_version", "agent_key", "config_version"),)

    config_id: Mapped[uuid.UUID] = uuid_pk()
    # NULL = the global "All LLM agents" switch
    agent_key: Mapped[str | None] = mapped_column(ForeignKey("agent_definition.agent_key"))
    enabled: Mapped[bool]
    previous_enabled: Mapped[bool | None]
    #: global, monotonically increasing across all agents; a run stores the version it started with
    config_version: Mapped[int] = mapped_column(index=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(server_default=text("false"))  # seeded demo toggle (D-54)


class AgentDecision(Timestamps, Base):
    __tablename__ = "agent_decision"
    __table_args__ = (
        Index("ix_agent_decision_agent_created", "agent_key", "created_at"),
        Index("ix_agent_decision_outcome", "outcome"),
        Index("ix_agent_decision_created", "created_at", "decision_id"),
        CheckConstraint(check_in("outcome", DecisionOutcome), name="outcome"),
        CheckConstraint(check_in("mode", RunMode), name="mode"),
    )

    decision_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    agent_key: Mapped[str] = mapped_column(ForeignKey("agent_definition.agent_key"))
    decision_type: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text, server_default=RunMode.LIVE.value)
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("store.store_id"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.product_id"), index=True)
    rec_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendation.rec_id"), index=True)
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transfer_order.transfer_id"), index=True
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order.po_id"), index=True)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_draft.draft_id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    outcome: Mapped[str] = mapped_column(Text, server_default=DecisionOutcome.PENDING.value)
    outcome_reason: Mapped[str | None] = mapped_column(Text)
    outcome_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentPreviewOutput(Timestamps, Base):
    __tablename__ = "agent_preview_output"

    preview_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    agent_key: Mapped[str] = mapped_column(Text)
    output_type: Mapped[str] = mapped_column(Text)  # RECOMMENDATION | REPLENISHMENT_NEED | TRANSFER | PO | …
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class AgentDraft(Timestamps, Base):
    __tablename__ = "agent_draft"
    __table_args__ = (
        CheckConstraint(check_in("status", DraftStatus), name="status"),
        CheckConstraint(check_in("mode", RunMode), name="mode"),
        CheckConstraint("qty IS NULL OR qty >= 0", name="qty"),
    )

    draft_id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    agent_key: Mapped[str] = mapped_column(ForeignKey("agent_definition.agent_key"), index=True)
    draft_type: Mapped[str] = mapped_column(Text)  # TRANSFER_DRAFT | PO_DRAFT | DATA_REVIEW_ITEM
    mode: Mapped[str] = mapped_column(Text, server_default=RunMode.LIVE.value)
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("store.store_id"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.product_id"), index=True)
    source_rec_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendation.rec_id"), index=True)
    qty: Mapped[int | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default=DraftStatus.DRAFT.value)


class RecommendationReview(Timestamps, Base):
    __tablename__ = "recommendation_review"
    __table_args__ = (CheckConstraint(check_in("verdict", ReviewVerdict), name="verdict"),)

    rec_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.rec_id"), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_run.run_id"), index=True)
    verdict: Mapped[str] = mapped_column(Text)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    judged_by: Mapped[str] = mapped_column(Text)  # "code" | "code+llm"


class PolicyDocument(Timestamps, Base):
    __tablename__ = "policy_document"
    __table_args__ = (Index("ix_policy_document_tsv", "search_tsv", postgresql_using="gin"),)

    section_id: Mapped[str] = mapped_column(Text, primary_key=True)  # "<doc>#<section-slug>"
    doc_name: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    heading: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(heading, '')), 'A') || "
            "to_tsvector('english', coalesce(body, ''))",
            persisted=True,
        ),
    )


class AgentEvalResult(Timestamps, Base):
    __tablename__ = "agent_eval_result"
    __table_args__ = (Index("ix_agent_eval_result_agent_created", "agent_key", "created_at"),)

    eval_id: Mapped[uuid.UUID] = uuid_pk()
    agent_key: Mapped[str] = mapped_column(ForeignKey("agent_definition.agent_key"))
    source: Mapped[str] = mapped_column(Text)  # RECORDED (CI, no live model) | LIVE
    variant: Mapped[str] = mapped_column(Text)  # AGENT | BASELINE
    cases: Mapped[int]
    correctness: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    groundedness: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    tool_use: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    failure_handling: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    latency_p50_ms: Mapped[int]
    latency_p95_ms: Mapped[int]
    tokens: Mapped[int]
    est_cost: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    human_agreement: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
