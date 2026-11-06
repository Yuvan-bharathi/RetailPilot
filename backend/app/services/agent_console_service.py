"""Read side of the agent console (docs/09 §3, D-50): overview stats, agent detail, runs and traces, decisions,
pipeline runs and the visual-flow graph. Keyset (cursor) paging on every unbounded list (spec §11)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, desc, func, or_, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AGENTS, BY_KEY, AgentSpec, get_spec
from app.core.config import REPO_ROOT
from app.core.errors import NotFound
from app.domain.models.agents import (
    AgentConfig,
    AgentDecision,
    AgentEvalResult,
    AgentPreviewOutput,
)
from app.domain.models.master import Product, Store
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun, LLMUsage, ToolCall
from app.domain.models.transfers import BusinessRule
from app.domain.models.users import AppUser
from app.domain.schemas.agents import (
    AgentDecisionDTO,
    AgentDetailDTO,
    AgentListDTO,
    AgentRunItemDTO,
    AgentRunPage,
    AgentRunTraceDTO,
    AgentStatsDTO,
    AgentStatusDTO,
    AgentSummaryDTO,
    DailyRunCountDTO,
    DecisionPage,
    DecisionStatDTO,
    EvalResultDTO,
    GraphEdgeDTO,
    GraphNodeDTO,
    LastRunRef,
    PipelinePage,
    PipelineRunDTO,
    PipelineStageDTO,
    PreviewOutputDTO,
    RuleValueDTO,
    RunGraphDTO,
    StoppingDTO,
    ToggleEventDTO,
    TraceStepDTO,
)
from app.domain.schemas.common import ProductRef, StoreRef
from app.domain.schemas.cursor import decode_keyset, encode_keyset
from app.services.agent_config_service import snapshot_async

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "agents" / "llm" / "prompts"

# Fixed layout of the visual flow (docs/09 §3.4): columns × rows, no physics. Same positions as the UI mock.
_COL = [20, 250, 480, 710, 940, 1170]  # 70 px gaps leave room for edge labels
_ROW = [20, 120, 220, 320, 420]
GRAPH_NODES: list[tuple[str, str, Literal["AGENT", "TOOL", "GATE", "DATA"], str | None, int, int]] = [
    ("ingestion", "POS ingestion", "DATA", None, 0, 2),
    ("data_quality", "Data Quality", "AGENT", "data_quality", 1, 0),
    ("sales_analytics", "Sales Analytics", "AGENT", "sales_analytics", 1, 1),
    ("demand_forecasting", "Demand Forecasting", "AGENT", "demand_forecasting", 1, 2),
    ("related_product", "Related Products", "AGENT", "related_product", 1, 3),
    ("stock_balancing", "Stock Balancing", "AGENT", "stock_balancing", 2, 2),
    ("tool_transfer_engine", "Transfer engine", "TOOL", None, 2, 1),
    ("freshness", "Freshness", "AGENT", "freshness", 3, 1),
    ("purchase_order", "Purchase Orders", "AGENT", "purchase_order", 3, 3),
    ("recommendation_reviewer", "Recommendation Reviewer", "AGENT", "recommendation_reviewer", 4, 2),
    ("gate_human", "Human approval", "GATE", None, 5, 2),
    ("run_coordinator", "Run Coordinator", "AGENT", "run_coordinator", 2, 4),
    ("replenishment_action", "Replenishment Action", "AGENT", "replenishment_action", 4, 4),
    ("ask_retailpilot", "Ask RetailPilot", "AGENT", "ask_retailpilot", 0, 4),
]
GRAPH_EDGES: list[GraphEdgeDTO] = [
    GraphEdgeDTO(source=s, target=t, label=lbl, kind=k)  # type: ignore[arg-type]
    for s, t, lbl, k in [
        ("ingestion", "data_quality", "issues", "EXCEPTION"),
        ("ingestion", "sales_analytics", None, "DATA"),
        ("ingestion", "demand_forecasting", "sales history", "DATA"),
        ("ingestion", "related_product", None, "DATA"),
        ("sales_analytics", "stock_balancing", "lost sales", "DATA"),
        ("demand_forecasting", "stock_balancing", "forecasts", "DATA"),
        ("related_product", "stock_balancing", "basket rules", "DATA"),
        ("demand_forecasting", "freshness", "forecasts", "DATA"),
        ("stock_balancing", "tool_transfer_engine", None, "DATA"),
        ("stock_balancing", "purchase_order", "PO needs", "DATA"),
        ("stock_balancing", "recommendation_reviewer", "recommendations", "REVIEW"),
        ("freshness", "recommendation_reviewer", None, "REVIEW"),
        ("purchase_order", "recommendation_reviewer", None, "REVIEW"),
        ("recommendation_reviewer", "gate_human", "inbox", "APPROVAL"),
        ("purchase_order", "run_coordinator", "run outcome", "EXCEPTION"),
        ("run_coordinator", "replenishment_action", "NEEDS_REVIEW", "EXCEPTION"),
        ("replenishment_action", "gate_human", "drafts", "APPROVAL"),
        ("data_quality", "gate_human", "review items", "APPROVAL"),
    ]
]

_ROOT_FILTER = and_(
    AgentRun.parent_run_id.is_(None),
    or_(AgentRun.agent_name == NIGHTLY_AGENT, AgentRun.agent_name.like("manual:%")),
)


def _duration_ms(r: AgentRun) -> int | None:
    return int((r.ended_at - r.started_at).total_seconds() * 1000) if r.ended_at and r.started_at else None


def _parse(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value


def _escalations(root: AgentRun) -> int:
    summary = _parse(root.output_summary)
    return int(summary.get("escalations", 0)) if isinstance(summary, dict) else 0


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


class AgentConsoleService:
    # --- overview ---------------------------------------------------------------------------------------------------

    async def _summaries(self, session: AsyncSession, keys: list[str] | None = None) -> list[AgentSummaryDTO]:
        snap = await snapshot_async(session)
        since = datetime.now(UTC) - timedelta(days=7)
        agent_runs = and_(
            AgentRun.agent_key.is_not(None),
            ~AgentRun.agent_name.like("manual:%"),
        )
        dur = AgentRun.duration_ms  # stored per run (D-54)
        stats = {
            k: (runs, ok, fin, p95)
            for k, runs, ok, fin, p95 in (
                await session.execute(
                    select(
                        AgentRun.agent_key,
                        func.count(),
                        func.count().filter(AgentRun.status == "SUCCESS"),
                        func.count().filter(AgentRun.status.in_(["SUCCESS", "FAILED", "PARTIAL"])),
                        func.percentile_cont(0.95)
                        .within_group(dur)
                        .filter(AgentRun.status.in_(["SUCCESS", "FAILED", "PARTIAL"])),
                    )
                    .where(agent_runs, AgentRun.started_at >= since)
                    .group_by(AgentRun.agent_key)
                )
            ).all()
        }
        usage = {
            k: (int(t or 0), Decimal(c or 0))
            for k, t, c in (
                await session.execute(
                    select(AgentRun.agent_key, func.sum(AgentRun.tokens), func.sum(AgentRun.est_cost_usd))
                    .where(agent_runs, AgentRun.started_at >= since)
                    .group_by(AgentRun.agent_key)
                )
            ).all()
        }
        last_rows = (
            await session.execute(
                select(AgentRun)
                .where(agent_runs)
                .ext(distinct_on(AgentRun.agent_key))
                .order_by(AgentRun.agent_key, desc(AgentRun.started_at))
            )
        ).scalars()
        last = {r.agent_key: r for r in last_rows}
        dec = {
            k: (int(recs or 0), int(acc or 0), int(decided or 0))
            for k, recs, acc, decided in (
                await session.execute(
                    select(
                        AgentDecision.agent_key,
                        func.count().filter(AgentDecision.created_at >= since),
                        func.count().filter(AgentDecision.outcome.in_(["ACCEPTED", "EDITED"])),
                        func.count().filter(AgentDecision.outcome.in_(["ACCEPTED", "EDITED", "REJECTED"])),
                    )
                    .where(AgentDecision.mode == "LIVE")
                    .group_by(AgentDecision.agent_key)
                )
            ).all()
        }
        out = []
        for a in AGENTS:
            if keys is not None and a.key not in keys:
                continue
            runs, ok, fin, p95 = stats.get(a.key, (0, 0, 0, None))
            tokens, cost = usage.get(a.key, (0, Decimal(0)))
            recs, acc, decided = dec.get(a.key, (0, 0, 0))
            lr = last.get(a.key)
            out.append(
                AgentSummaryDTO(
                    agent_key=a.key,
                    name=a.name,
                    group=a.group,
                    kind=a.kind,
                    pattern=a.pattern,
                    critical=a.critical,
                    purpose=a.purpose,
                    enabled=snap.enabled.get(a.key, True),
                    effective_enabled=snap.is_on(a.key),
                    depends_on=list(a.depends_on),
                    optional_inputs=list(a.optional_inputs),
                    triggerable=a.triggerable,
                    last_run=LastRunRef(
                        run_id=lr.run_id,
                        status=lr.status,  # type: ignore[arg-type]
                        started_at=lr.started_at,
                        finished_at=lr.ended_at,
                    )
                    if lr
                    else None,
                    runs_7d=int(runs),
                    success_rate_7d=_rate(int(ok), int(fin)),
                    p95_latency_ms=int(p95) if p95 is not None else None,
                    tokens_7d=tokens,
                    est_cost_7d_usd=cost,
                    recommendations_7d=recs,
                    acceptance_rate=_rate(acc, decided),
                )
            )
        return out

    async def paused_banner(self, session: AsyncSession, snap: Any = None) -> str | None:
        snap = snap or await snapshot_async(session)
        off = [
            a for a in AGENTS if a.group == "PIPELINE" and a.critical and not snap.enabled.get(a.key, True)
        ]
        if not off:
            return None
        row = (
            await session.execute(
                select(AgentConfig, AppUser.name)
                .outerjoin(AppUser, AppUser.user_id == AgentConfig.updated_by)
                .where(AgentConfig.agent_key == off[0].key)
                .order_by(desc(AgentConfig.config_version))
                .limit(1)
            )
        ).first()
        who, why = (
            (row[1] or "Super Admin", row[0].reason) if row else ("Super Admin", f"{off[0].name} is off")
        )
        return f"Replenishment paused by {who}: {why}"

    async def status(self, session: AsyncSession) -> AgentStatusDTO:
        snap = await snapshot_async(session)
        return AgentStatusDTO(
            expiry_checks_on=snap.is_on("freshness"),
            reviewer_on=snap.is_on("recommendation_reviewer"),
            ask_enabled=snap.is_on("ask_retailpilot"),
            replenishment_paused=await self.paused_banner(session, snap),
        )

    async def list_agents(self, session: AsyncSession) -> AgentListDTO:
        snap = await snapshot_async(session)
        return AgentListDTO(
            items=await self._summaries(session),
            llm_enabled=snap.llm_enabled,
            config_version=snap.version,
            paused_banner=await self.paused_banner(session, snap),
        )

    async def get_agent(self, session: AsyncSession, agent_key: str) -> AgentDetailDTO:
        spec = get_spec(agent_key)
        if spec is None:
            raise NotFound(f"Unknown agent {agent_key}")
        [summary] = await self._summaries(session, [agent_key])
        history = [
            ToggleEventDTO(
                config_version=c.config_version,
                agent_key=c.agent_key,
                enabled=c.enabled,
                previous_enabled=c.previous_enabled,
                reason=c.reason,
                updated_by=name,
                created_at=c.created_at,
                is_demo=c.is_demo,
            )
            for c, name in (
                await session.execute(
                    select(AgentConfig, AppUser.name)
                    .outerjoin(AppUser, AppUser.user_id == AgentConfig.updated_by)
                    .where(or_(AgentConfig.agent_key == agent_key, AgentConfig.agent_key.is_(None)))
                    .order_by(desc(AgentConfig.config_version), desc(AgentConfig.created_at))
                    .limit(50)
                )
            ).all()
        ]
        rules: list[RuleValueDTO] = []
        if spec.business_rules:
            rows = await session.execute(
                select(BusinessRule.rule_key, BusinessRule.value).where(
                    BusinessRule.rule_key.in_(spec.business_rules), BusinessRule.scope_store_id.is_(None)
                )
            )
            rules = [RuleValueDTO(key=k, value=v) for k, v in rows.all()]
        evals = await self._latest_evals(session, agent_key)
        card = REPO_ROOT / spec.card_path
        prompt = PROMPTS_DIR / f"{spec.prompt_version}.md" if spec.prompt_version else None
        return AgentDetailDTO(
            agent=summary,
            delegation=spec.delegation,
            description=spec.description,
            discernment=spec.discernment,
            diligence=spec.diligence,
            input_contract=spec.input_contract,
            output_contract=spec.output_contract,
            read_tools=list(spec.read_tools),
            draft_tools=list(spec.draft_tools),
            stopping=StoppingDTO(
                max_tool_calls=spec.stopping.max_tool_calls,
                max_tokens=spec.stopping.max_tokens,
                timeout_s=spec.stopping.timeout_s,
                other=list(spec.stopping.other),
            ),
            prompt_version=spec.prompt_version,
            prompt_text=prompt.read_text(encoding="utf-8") if prompt and prompt.exists() else None,
            business_rules=rules,
            disabled_effect=spec.disabled_effect,
            human_in_the_loop=spec.human_in_the_loop,
            decision_types=list(spec.decision_types),
            card_markdown=card.read_text(encoding="utf-8") if card.exists() else None,
            toggle_history=history,
            evals=evals,
        )

    async def _latest_evals(self, session: AsyncSession, agent_key: str) -> list[EvalResultDTO]:
        rows = (
            await session.execute(
                select(AgentEvalResult)
                .where(AgentEvalResult.agent_key == agent_key)
                .ext(distinct_on(AgentEvalResult.source, AgentEvalResult.variant))
                .order_by(AgentEvalResult.source, AgentEvalResult.variant, desc(AgentEvalResult.created_at))
            )
        ).scalars()
        return [
            EvalResultDTO(
                agent_key=e.agent_key,
                source=e.source,  # type: ignore[arg-type]
                variant=e.variant,  # type: ignore[arg-type]
                cases=e.cases,
                correctness=float(e.correctness),
                groundedness=float(e.groundedness),
                tool_use=float(e.tool_use),
                failure_handling=float(e.failure_handling),
                latency_p50_ms=e.latency_p50_ms,
                latency_p95_ms=e.latency_p95_ms,
                tokens=e.tokens,
                est_cost_usd=e.est_cost,
                human_agreement=float(e.human_agreement) if e.human_agreement is not None else None,
                created_at=e.created_at,
            )
            for e in rows
        ]

    async def agent_stats(self, session: AsyncSession, agent_key: str, days: int) -> AgentStatsDTO:
        if get_spec(agent_key) is None:
            raise NotFound(f"Unknown agent {agent_key}")
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date(AgentRun.started_at)
        rows = await session.execute(
            select(
                day,
                func.count().filter(AgentRun.status == "SUCCESS"),
                func.count().filter(AgentRun.status == "FAILED"),
                func.count().filter(AgentRun.status.not_in(["SUCCESS", "FAILED"])),
            )
            .where(
                AgentRun.agent_key == agent_key,
                AgentRun.started_at >= since,
                ~AgentRun.agent_name.like("manual:%"),
            )
            .group_by(day)
            .order_by(day)
        )
        dur = AgentRun.duration_ms
        p50, p95 = (
            await session.execute(
                select(
                    func.percentile_cont(0.5).within_group(dur), func.percentile_cont(0.95).within_group(dur)
                ).where(
                    AgentRun.agent_key == agent_key,
                    AgentRun.started_at >= since,
                    AgentRun.ended_at.is_not(None),
                    AgentRun.status.in_(["SUCCESS", "FAILED", "PARTIAL"]),
                )
            )
        ).one()
        return AgentStatsDTO(
            agent_key=agent_key,
            runs_by_day=[DailyRunCountDTO(day=d, success=s, failed=f, other=o) for d, s, f, o in rows.all()],
            latency_p50_ms=int(p50) if p50 is not None else None,
            latency_p95_ms=int(p95) if p95 is not None else None,
            decisions_by_type=await self.decision_stats(session, agent_key),
        )

    # --- runs and traces ------------------------------------------------------------------------------------------

    async def _items(self, session: AsyncSession, runs: list[AgentRun]) -> list[AgentRunItemDTO]:
        if not runs:
            return []
        users = {r.triggered_by for r in runs if r.triggered_by}
        names = (
            dict(
                (
                    await session.execute(
                        select(AppUser.user_id, AppUser.name).where(AppUser.user_id.in_(users))
                    )
                ).all()
            )
            if users
            else {}
        )
        out = []
        for r in runs:
            spec = BY_KEY.get(r.agent_key or "")
            label = (
                "Nightly pipeline"
                if r.agent_name == NIGHTLY_AGENT
                else f"Manual: {spec.name}"
                if r.agent_name.startswith("manual:") and spec
                else spec.name
                if spec
                else r.agent_name
            )
            out.append(
                AgentRunItemDTO(
                    run_id=r.run_id,
                    parent_run_id=r.parent_run_id,
                    agent_key=r.agent_key,
                    agent_name=label,
                    trigger_type=r.trigger_type,  # type: ignore[arg-type]
                    mode=r.mode,  # type: ignore[arg-type]
                    status=r.status,  # type: ignore[arg-type]
                    run_date=r.run_date,
                    started_at=r.started_at,
                    finished_at=r.ended_at,
                    duration_ms=r.duration_ms if r.duration_ms is not None else _duration_ms(r),
                    tool_calls=r.tool_calls_count or 0,
                    llm_calls=r.llm_calls_count or 0,
                    tokens=r.tokens or 0,
                    est_cost_usd=r.est_cost_usd or Decimal(0),
                    retries=r.retries,
                    stop_reason=r.stop_reason,
                    error=r.error,
                    triggered_by=names.get(r.triggered_by) if r.triggered_by else None,
                    reason=r.reason,
                    is_demo=r.is_demo,
                )
            )
        return out

    async def list_runs(
        self,
        session: AsyncSession,
        *,
        cursor: str | None,
        page_size: int,
        agent_key: str | None,
        status: str | None,
        trigger_type: str | None,
        date_from: date | None,
        date_to: date | None,
        roots_only: bool,
    ) -> AgentRunPage:
        stmt = select(AgentRun)
        if agent_key:
            stmt = stmt.where(AgentRun.agent_key == agent_key)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        if trigger_type:
            stmt = stmt.where(AgentRun.trigger_type == trigger_type)
        if date_from:
            stmt = stmt.where(AgentRun.started_at >= datetime.combine(date_from, datetime.min.time(), UTC))
        if date_to:
            stmt = stmt.where(
                AgentRun.started_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), UTC)
            )
        if roots_only:
            stmt = stmt.where(AgentRun.parent_run_id.is_(None))
        if cursor:
            c = decode_keyset(cursor)
            stmt = stmt.where(
                or_(AgentRun.started_at < c.at, and_(AgentRun.started_at == c.at, AgentRun.run_id < c.row_id))
            )
        rows = list(
            (
                await session.execute(
                    stmt.order_by(desc(AgentRun.started_at), desc(AgentRun.run_id)).limit(page_size + 1)
                )
            )
            .scalars()
            .all()
        )
        nxt = (
            encode_keyset(rows[page_size - 1].started_at, rows[page_size - 1].run_id)
            if len(rows) > page_size
            else None
        )
        return AgentRunPage(
            items=await self._items(session, rows[:page_size]), next_cursor=nxt, page_size=page_size
        )

    async def get_trace(self, session: AsyncSession, run_id: UUID) -> AgentRunTraceDTO:
        run = await session.get(AgentRun, run_id)
        if run is None:
            raise NotFound(f"Agent run {run_id} not found")
        children = list(
            (
                await session.execute(
                    select(AgentRun).where(AgentRun.parent_run_id == run_id).order_by(AgentRun.started_at)
                )
            ).scalars()
        )
        [item] = await self._items(session, [run])
        child_items = await self._items(session, children)
        steps: list[TraceStepDTO] = []
        for tc in (
            await session.execute(
                select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at)
            )
        ).scalars():
            steps.append(
                TraceStepDTO(
                    kind="TOOL",
                    at=tc.created_at,
                    name=tc.tool_name,
                    status=tc.status,
                    duration_ms=tc.duration_ms,
                    args_summary=json.dumps(tc.args, default=str)[:400] if tc.args else None,
                    result_summary=(tc.result_summary or "")[:600] or None,
                )
            )
        for u in (
            await session.execute(
                select(LLMUsage).where(LLMUsage.run_id == run_id).order_by(LLMUsage.created_at)
            )
        ).scalars():
            steps.append(
                TraceStepDTO(
                    kind="LLM",
                    at=u.created_at,
                    name="chat completion",
                    status="OK",
                    duration_ms=u.latency_ms,
                    model=u.model,
                    input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens,
                    est_cost_usd=u.est_cost,
                )
            )
        for c, ci in zip(children, child_items, strict=True):
            steps.append(
                TraceStepDTO(
                    kind="CHILD_RUN",
                    at=c.started_at,
                    name=ci.agent_name,
                    status=c.status,
                    duration_ms=ci.duration_ms,
                    run_id=c.run_id,
                    result_summary=c.error or c.stop_reason,
                )
            )
        steps.sort(key=lambda s: s.at)
        if run.error:
            steps.append(
                TraceStepDTO(
                    kind="ERROR",
                    at=run.ended_at or run.started_at,
                    name="error",
                    status="ERROR",
                    result_summary=run.error[:600],
                )
            )
        if run.status != "RUNNING":
            steps.append(
                TraceStepDTO(
                    kind="STOP",
                    at=run.ended_at or run.started_at,
                    name="stop",
                    status=run.status,
                    result_summary=run.stop_reason,
                )
            )
        previews = [
            PreviewOutputDTO(agent_key=p.agent_key, output_type=p.output_type, payload=p.payload)
            for p in (
                await session.execute(
                    select(AgentPreviewOutput).where(AgentPreviewOutput.run_id == run_id).limit(200)
                )
            ).scalars()
        ]
        n_decisions = (
            run.decisions_count
            if run.decisions_count is not None
            else await session.scalar(
                select(func.count()).select_from(AgentDecision).where(AgentDecision.run_id == run_id)
            )
        )
        return AgentRunTraceDTO(
            run=item,
            input_ref=run.input_ref or {},
            output_summary=_parse(run.output_summary),
            config_version=run.config_version,
            config_snapshot=run.config_snapshot,
            children=child_items,
            steps=steps,
            previews=previews,
            decisions=int(n_decisions or 0),
        )

    # --- decisions --------------------------------------------------------------------------------------------------

    async def list_decisions(
        self,
        session: AsyncSession,
        *,
        cursor: str | None,
        page_size: int,
        agent_key: str | None,
        decision_type: str | None,
        outcome: str | None,
        store_id: UUID | None,
        mode: str | None,
        run_id: UUID | None,
        q: str | None,
    ) -> DecisionPage:
        stmt = (
            select(AgentDecision, Store, Product, AgentRun.is_demo)
            .join(AgentRun, AgentRun.run_id == AgentDecision.run_id)
            .outerjoin(Store, Store.store_id == AgentDecision.store_id)
            .outerjoin(Product, Product.product_id == AgentDecision.product_id)
        )
        for col, val in (
            (AgentDecision.agent_key, agent_key),
            (AgentDecision.decision_type, decision_type),
            (AgentDecision.outcome, outcome),
            (AgentDecision.store_id, store_id),
            (AgentDecision.mode, mode),
        ):
            if val:
                stmt = stmt.where(col == val)
        if run_id:  # a root run: its own decisions and those of its child runs
            stmt = stmt.where(
                or_(
                    AgentDecision.run_id == run_id,
                    AgentDecision.run_id.in_(select(AgentRun.run_id).where(AgentRun.parent_run_id == run_id)),
                )
            )
        if q:
            term = f"%{q.strip()}%"
            stmt = stmt.where(or_(AgentDecision.summary.ilike(term), Product.name.ilike(term)))
        if cursor:
            c = decode_keyset(cursor)
            stmt = stmt.where(
                or_(
                    AgentDecision.created_at < c.at,
                    and_(AgentDecision.created_at == c.at, AgentDecision.decision_id < c.row_id),
                )
            )
        rows = (
            await session.execute(
                stmt.order_by(desc(AgentDecision.created_at), desc(AgentDecision.decision_id)).limit(
                    page_size + 1
                )
            )
        ).all()
        items = [
            AgentDecisionDTO(
                decision_id=d.decision_id,
                run_id=d.run_id,
                agent_key=d.agent_key,
                agent_name=BY_KEY[d.agent_key].name if d.agent_key in BY_KEY else d.agent_key,
                decision_type=d.decision_type,
                mode=d.mode,  # type: ignore[arg-type]
                store=StoreRef(store_id=s.store_id, name=s.name) if s else None,
                product=ProductRef(product_id=p.product_id, sku=p.sku, name=p.name, category=p.category)
                if p
                else None,
                summary=d.summary,
                rec_id=d.rec_id,
                transfer_id=d.transfer_id,
                po_id=d.po_id,
                draft_id=d.draft_id,
                evidence_ref=d.evidence_ref or {},
                outcome=d.outcome,  # type: ignore[arg-type]
                outcome_reason=d.outcome_reason,
                outcome_at=d.outcome_at,
                created_at=d.created_at,
                is_demo=bool(demo),
            )
            for d, s, p, demo in rows[:page_size]
        ]
        last = rows[page_size - 1][0] if len(rows) > page_size else None
        return DecisionPage(
            items=items,
            next_cursor=encode_keyset(last.created_at, last.decision_id) if last else None,
            page_size=page_size,
        )

    async def decision_stats(self, session: AsyncSession, agent_key: str | None) -> list[DecisionStatDTO]:
        stmt = (
            select(
                AgentDecision.agent_key,
                AgentDecision.decision_type,
                func.count(),
                *[
                    func.count().filter(AgentDecision.outcome == o)
                    for o in ("ACCEPTED", "EDITED", "REJECTED", "PENDING", "SUPERSEDED")
                ],
            )
            .where(AgentDecision.mode == "LIVE")
            .group_by(AgentDecision.agent_key, AgentDecision.decision_type)
            .order_by(AgentDecision.agent_key, AgentDecision.decision_type)
        )
        if agent_key:
            stmt = stmt.where(AgentDecision.agent_key == agent_key)
        out: list[DecisionStatDTO] = []
        for row in (await session.execute(stmt)).all():
            k, t = str(row[0]), str(row[1])
            n, a, e, r, p, sup = (int(x or 0) for x in row[2:8])
            out.append(
                DecisionStatDTO(
                    agent_key=k,
                    decision_type=t,
                    total=n,
                    accepted=a,
                    edited=e,
                    rejected=r,
                    pending=p,
                    superseded=sup,
                    acceptance_rate=_rate(a + e, a + e + r),
                )
            )
        return out

    # --- pipeline and graph ---------------------------------------------------------------------------------------

    async def list_pipeline_runs(
        self,
        session: AsyncSession,
        *,
        cursor: str | None,
        page_size: int,
        trigger_type: str | None,
        status: str | None,
    ) -> PipelinePage:
        stmt = select(AgentRun).where(_ROOT_FILTER)
        if trigger_type:
            stmt = stmt.where(AgentRun.trigger_type == trigger_type)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        if cursor:
            c = decode_keyset(cursor)
            stmt = stmt.where(
                or_(AgentRun.started_at < c.at, and_(AgentRun.started_at == c.at, AgentRun.run_id < c.row_id))
            )
        roots = list(
            (
                await session.execute(
                    stmt.order_by(desc(AgentRun.started_at), desc(AgentRun.run_id)).limit(page_size + 1)
                )
            )
            .scalars()
            .all()
        )
        page = roots[:page_size]
        ids = [r.run_id for r in page]
        children: dict[UUID, list[AgentRun]] = {i: [] for i in ids}
        if ids:
            for child in (
                await session.execute(
                    select(AgentRun).where(AgentRun.parent_run_id.in_(ids)).order_by(AgentRun.started_at)
                )
            ).scalars():
                if child.parent_run_id is not None:
                    children[child.parent_run_id].append(child)
        users = {r.triggered_by for r in page if r.triggered_by}
        names = (
            dict(
                (
                    await session.execute(
                        select(AppUser.user_id, AppUser.name).where(AppUser.user_id.in_(users))
                    )
                ).all()
            )
            if users
            else {}
        )
        items = []
        for r in page:
            stages = [
                PipelineStageDTO(
                    agent_key=c.agent_key or "",
                    name=BY_KEY[c.agent_key].name if c.agent_key in BY_KEY else c.agent_name,
                    status=c.status,  # type: ignore[arg-type]
                    run_id=c.run_id,
                    duration_ms=_duration_ms(c),
                    retries=c.retries,
                    outputs=c.decisions_count if c.status == "SUCCESS" else None,
                    error=c.error,
                )
                for c in children[r.run_id]
            ]
            items.append(
                PipelineRunDTO(
                    run_id=r.run_id,
                    run_date=r.run_date,
                    agent_key=r.agent_key,
                    trigger_type=r.trigger_type,  # type: ignore[arg-type]
                    mode=r.mode,  # type: ignore[arg-type]
                    status=r.status,  # type: ignore[arg-type]
                    started_at=r.started_at,
                    finished_at=r.ended_at,
                    duration_ms=_duration_ms(r),
                    config_version=r.config_version,
                    triggered_by=names.get(r.triggered_by) if r.triggered_by else None,
                    reason=r.reason,
                    stop_reason=r.stop_reason,
                    stages=stages,
                    escalations=_escalations(r),
                    has_partial=r.status == "PARTIAL" or any(s.status == "FAILED" for s in stages),
                    is_demo=r.is_demo,
                )
            )
        nxt = encode_keyset(page[-1].started_at, page[-1].run_id) if len(roots) > page_size else None
        return PipelinePage(items=items, next_cursor=nxt, page_size=page_size)

    async def run_graph(self, session: AsyncSession, run_id: UUID | str) -> RunGraphDTO:
        if run_id == "latest":
            root = (
                await session.execute(
                    select(AgentRun).where(_ROOT_FILTER).order_by(desc(AgentRun.started_at)).limit(1)
                )
            ).scalar_one_or_none()
        else:
            root = await session.get(AgentRun, run_id)
        if root is None:
            raise NotFound("Run not found")
        children = list(
            (
                await session.execute(
                    select(AgentRun)
                    .where(AgentRun.parent_run_id == root.run_id)
                    .order_by(AgentRun.started_at)
                )
            ).scalars()
        )
        by_key: dict[str, AgentRun] = {}
        for c in children:  # a retry is a later child of the same agent: the last attempt wins
            if c.agent_key:
                by_key[c.agent_key] = c
        pending = await session.scalar(
            select(func.count())
            .select_from(AgentDecision)
            .where(AgentDecision.run_id == root.run_id, AgentDecision.outcome == "PENDING")
        )
        in_progress = root.status == "RUNNING"
        reused = {
            u.get("agent_key")
            for u in (root.input_ref or {}).get("upstream", [])
            if isinstance(u, dict) and u.get("action") == "REUSE"
        }
        nodes = []
        for nid, label, ntype, key, col, row in GRAPH_NODES:
            child = by_key.get(key) if key else None
            if ntype == "AGENT":
                status: Any = (
                    child.status if child else ("RUNNING" if in_progress and key in BY_KEY else "NOT_RUN")
                )
                if child is None and in_progress:
                    status = "NOT_RUN"
                if child is None and key in reused:
                    status = "DONE"  # a manual run reused this agent's outputs from the nightly run (D-51)
            elif ntype == "GATE":
                status = "NOT_RUN" if root.mode == "DRY_RUN" else "WAITING" if pending else "DONE"
            elif ntype == "TOOL":
                sb = by_key.get("stock_balancing")
                status = "DONE" if sb and sb.status == "SUCCESS" else "NOT_RUN"
            else:
                status = "DONE"
            detail = None
            if child:
                retries = (
                    f" · {child.retries} retr{'y' if child.retries == 1 else 'ies'}" if child.retries else ""
                )
                detail = f"{(child.duration_ms or _duration_ms(child) or 0) / 1000:.1f} s · {child.tool_calls_count or 0} tool calls{retries}"
                if child.error:
                    detail += f" · {child.error[:120]}"
            elif key in reused:
                detail = "Outputs reused from the latest nightly run"
            elif key == "ask_retailpilot":
                detail = "On demand (questions)"
            elif ntype == "GATE":
                detail = (
                    f"{int(pending or 0)} decisions waiting for people" if pending else "No pending decisions"
                )
            nodes.append(
                GraphNodeDTO(
                    id=nid,
                    label=label,
                    node_type=ntype,
                    agent_key=key,
                    status=status,
                    run_id=child.run_id if child else None,
                    x=_COL[col],
                    y=_ROW[row],
                    detail=detail,
                )
            )
        return RunGraphDTO(
            run_id=root.run_id,
            status=root.status,  # type: ignore[arg-type]
            in_progress=in_progress,
            nodes=nodes,
            edges=GRAPH_EDGES,
        )


def spec_or_404(agent_key: str) -> AgentSpec:
    spec = get_spec(agent_key)
    if spec is None:
        raise NotFound(f"Unknown agent {agent_key}")
    return spec


_ = text  # re-exported for raw SQL helpers in tests
