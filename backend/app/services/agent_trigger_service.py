"""Per-agent "Run now" (docs/09 §3.6, D-50).

- DRY_RUN (default): the agent runs on the latest data inside a SAVEPOINT; its outputs (recommendations, needs,
  transfers, POs, drafts, reviews, decisions) are copied into `agent_preview_output` and the savepoint is rolled
  back — nothing reaches the inbox, POs, transfers, dashboards or the cache. Run logs are kept.
- LIVE: Super Admin + reason + confirmation; publishes like a nightly stage: pending outputs of the re-run agents
  are superseded first, downstream dependants re-run, views refreshed, cache invalidated.
- Upstream inputs: agent outputs are keyed by the run that produced them, so a manual run gets its own root run.
  Data-only upstream outputs (forecasts, lost sales/KPIs, basket rules) of the latest nightly run are REUSED (copied)
  when that run is for the current planning day, else the upstream agent is RE-RUN; stock balancing (needs and
  recommendations) is never copied, it is re-run.
- Blocked when the agent is disabled, a run is in progress, or 3 live triggers of the agent in the last hour.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.agents.registry import BY_KEY, PIPELINE_KEYS, downstream_dependants, get_spec, upstream_closure
from app.core.errors import ConflictError, ErrorDetail, NotFound, ValidationError
from app.domain.models.agents import AgentDecision, AgentDraft, AgentPreviewOutput, RecommendationReview
from app.domain.models.enums import LineStatus, POStatus, RecStatus, TransferStatus
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun, LLMUsage, ToolCall
from app.domain.models.planning import Recommendation, ReplenishmentNeed
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.transfers import TransferOrder
from app.domain.models.users import AppUser
from app.domain.schemas.agents import (
    AgentRunItemDTO,
    TriggerAgentRequest,
    TriggerPreviewDTO,
    TriggerResultDTO,
    UpstreamStatusDTO,
)
from app.services.agent_config_service import snapshot, snapshot_async

logger = logging.getLogger(__name__)

LIVE_LIMIT_PER_HOUR = 3
#: upstream outputs that can be copied from the latest nightly run (data only, no inbox items)
COPYABLE: dict[str, list[tuple[str, str]]] = {
    "demand_forecasting": [
        ("forecast", "store_id, product_id, horizon_days, daily_demand, method, confidence"),
    ],
    "sales_analytics": [
        ("lost_sales_estimate", "store_id, product_id, lost_units, lost_revenue, lost_profit, confidence"),
        ("kpi_snapshot", "store_id, metric, product_key, value"),
    ],
    "related_product": [
        ("association_rule", "store_id, antecedent_id, consequent_id, support, confidence, lift, rule_type"),
    ],
}


def _latest_nightly_stmt() -> Any:
    return (
        select(AgentRun)
        .where(AgentRun.agent_name == NIGHTLY_AGENT, AgentRun.status.in_(["SUCCESS", "PARTIAL"]))
        .order_by(desc(AgentRun.started_at))
        .limit(1)
    )


_ROOT_RUNNING = (
    select(func.count())
    .select_from(AgentRun)
    .where(
        AgentRun.parent_run_id.is_(None),
        AgentRun.status == "RUNNING",
        (AgentRun.agent_name == NIGHTLY_AGENT) | AgentRun.agent_name.like("manual:%"),
    )
)


class AgentTriggerService:
    async def _plan(
        self, session: AsyncSession, key: str
    ) -> tuple[list[UpstreamStatusDTO], AgentRun | None, date | None]:
        spec = BY_KEY[key]
        latest = (await session.execute(_latest_nightly_stmt())).scalar_one_or_none()
        max_day = await session.scalar(text("SELECT max(snapshot_date) FROM inventory_daily_snapshot"))
        planning_day = max_day + timedelta(days=1) if max_day else None
        fresh_run = latest is not None and planning_day is not None and latest.run_date == planning_day
        ok_children: set[str] = set()
        if latest is not None:
            ok_children = {
                k
                for k in (
                    await session.execute(
                        select(AgentRun.agent_key).where(
                            AgentRun.parent_run_id == latest.run_id, AgentRun.status == "SUCCESS"
                        )
                    )
                ).scalars()
                if k
            }
        snap = await snapshot_async(session)
        ups: list[UpstreamStatusDTO] = []
        deps = upstream_closure(key) if spec.group == "PIPELINE" else list(spec.depends_on)
        for d in deps:
            if not snap.is_on(d):
                ups.append(UpstreamStatusDTO(agent_key=d, fresh=False, action="SKIP_DISABLED"))
                continue
            fresh = fresh_run and d in ok_children
            if spec.kind == "LLM":  # LLM agents read the latest nightly outputs in place
                ups.append(UpstreamStatusDTO(agent_key=d, fresh=d in ok_children, action="REUSE"))
            elif d in COPYABLE and fresh:
                ups.append(UpstreamStatusDTO(agent_key=d, fresh=True, action="REUSE"))
            else:
                ups.append(UpstreamStatusDTO(agent_key=d, fresh=fresh, action="RERUN"))
        if spec.group == "PIPELINE":  # optional inputs (lost sales, basket rules) are reused or re-run too
            for o in spec.optional_inputs:
                if o in deps or not snap.is_on(o):
                    continue
                fresh = fresh_run and o in ok_children
                ups.append(UpstreamStatusDTO(agent_key=o, fresh=fresh, action="REUSE" if fresh else "RERUN"))
        return ups, latest, planning_day

    async def preview(self, session: AsyncSession, key: str, mode: str) -> TriggerPreviewDTO:
        spec = get_spec(key)
        if spec is None:
            raise NotFound(f"Unknown agent {key}")
        snap = await snapshot_async(session)
        ups, latest, _ = await self._plan(session, key)
        downstream = (
            [d for d in downstream_dependants(key) if d in PIPELINE_KEYS] if spec.group == "PIPELINE" else []
        )
        since = datetime.now(UTC) - timedelta(hours=1)
        live_count = int(
            await session.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.agent_name == f"manual:{key}",
                    AgentRun.trigger_type == "MANUAL_LIVE",
                    AgentRun.started_at >= since,
                )
            )
            or 0
        )
        running = int(await session.scalar(_ROOT_RUNNING) or 0)
        affected = [key, *downstream]
        to_supersede = 0
        if mode == "LIVE" and spec.group == "PIPELINE":
            to_supersede = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Recommendation)
                    .where(
                        Recommendation.status == RecStatus.PENDING.value,
                        Recommendation.rec_id.in_(
                            select(AgentDecision.rec_id).where(
                                AgentDecision.agent_key.in_(affected), AgentDecision.mode == "LIVE"
                            )
                        ),
                    )
                )
                or 0
            )
        blocked = None
        if not spec.triggerable:
            blocked = "This agent is triggered by questions on the Ask RetailPilot page"
        elif not snap.is_on(key):
            blocked = "The agent is disabled" + (
                " (all LLM agents are off)" if spec.kind == "LLM" and not snap.llm_enabled else ""
            )
        elif running:
            blocked = "A run is in progress — wait for it to finish"
        elif any(u.action == "SKIP_DISABLED" and u.agent_key in spec.depends_on for u in ups):
            blocked = "A required upstream agent is disabled"
        elif spec.kind == "LLM" and latest is None:
            blocked = "No nightly run yet — there is nothing to work on"
        elif mode == "LIVE" and live_count >= LIVE_LIMIT_PER_HOUR:
            blocked = f"Rate limit: {LIVE_LIMIT_PER_HOUR} live triggers per agent per hour"
        if mode == "LIVE":
            cons = (
                [
                    f"Pending recommendations of {', '.join(BY_KEY[a].name for a in affected)} are superseded",
                    f"Downstream agents re-run: {', '.join(downstream)}"
                    if downstream
                    else "No downstream agent re-runs",
                    "New outputs reach the inbox, POs and transfers like a nightly stage",
                ]
                if spec.group == "PIPELINE"
                else [
                    f"{spec.name} works on the latest nightly run and writes its outputs (drafts, reviews, decisions)",
                    "Nothing is approved or submitted: people decide through the existing approvals",
                ]
            )
        else:
            cons = [
                "Outputs are stored in a preview set only — inbox, POs, transfers, dashboards and cache do not change"
            ]
            if downstream:
                cons.append(f"Downstream agents are not re-run in a dry run: {', '.join(downstream)}")
        reruns = [u.agent_key for u in ups if u.action == "RERUN"]
        if reruns:
            cons.append(f"Stale or non-reusable upstream inputs are re-run first: {', '.join(reruns)}")
        return TriggerPreviewDTO(
            agent_key=key,
            mode=mode,  # type: ignore[arg-type]
            allowed=blocked is None,
            blocked_reason=blocked,
            upstream=ups,
            downstream=downstream,
            recommendations_to_supersede=to_supersede,
            live_triggers_last_hour=live_count,
            live_trigger_limit=LIVE_LIMIT_PER_HOUR,
            consequences=cons,
        )

    async def start(
        self, session: AsyncSession, key: str, body: TriggerAgentRequest, user: AppUser
    ) -> TriggerResultDTO:
        if body.mode == "LIVE":
            missing: list[ErrorDetail] = []
            if not body.reason or len(body.reason.strip()) < 5:
                missing.append(ErrorDetail(field="reason", message="required for a live run"))
            if not body.confirm:
                missing.append(ErrorDetail(field="confirm", message="confirm the consequences"))
            if missing:
                raise ValidationError("A live run needs a reason and confirmation", details=missing)
        preview = await self.preview(session, key, body.mode)
        if not preview.allowed:
            raise ConflictError(preview.blocked_reason or "Blocked")
        ups, latest, planning_day = await self._plan(session, key)
        snap = await snapshot_async(session)
        run_id = uuid.uuid4()
        session.add(
            AgentRun(
                run_id=run_id,
                parent_run_id=None,
                agent_name=f"manual:{key}",
                agent_key=key,
                run_date=planning_day,
                status="RUNNING",
                started_at=datetime.now(UTC),
                trigger_type="MANUAL_LIVE" if body.mode == "LIVE" else "MANUAL_DRY_RUN",
                mode=body.mode,
                triggered_by=user.user_id,
                reason=(body.reason or "").strip() or None,
                config_version=snap.version,
                config_snapshot=snap.as_json(),
                input_ref={
                    "agent_key": key,
                    "mode": body.mode,
                    "source_run_id": str(latest.run_id) if latest else None,
                    "upstream": [u.model_dump() for u in ups],
                    "downstream": preview.downstream,
                },
            )
        )
        await session.commit()
        return TriggerResultDTO(
            run_id=run_id,
            mode=body.mode,
            status="RUNNING",
            message=f"{BY_KEY[key].name}: {body.mode} run started",
        )

    async def cancel(self, session: AsyncSession, run_id: UUID, user: AppUser) -> AgentRunItemDTO:
        from app.services.agent_console_service import AgentConsoleService

        run = await session.get(AgentRun, run_id)
        if run is None:
            raise NotFound("Agent run not found")
        if run.parent_run_id is not None or run.status != "RUNNING":
            raise ConflictError("Only a running pipeline or manual run can be cancelled")
        run.cancel_requested = True
        run.stop_reason = f"cancel requested by {user.name}"
        await session.commit()
        [item] = await AgentConsoleService()._items(session, [run])
        return item


# --- background execution ------------------------------------------------------------------------------------------


def run_trigger_in_background(run_id: UUID) -> None:
    from app.core.db import get_sync_session_factory

    with get_sync_session_factory()() as session:
        try:
            ManualRunner(session).execute(run_id)
        except Exception as exc:  # defined outcome: the root run is marked FAILED, never left RUNNING
            logger.exception("manual run %s failed", run_id)
            session.rollback()
            session.execute(
                update(AgentRun)
                .where(AgentRun.run_id == run_id)
                .values(
                    status="FAILED",
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    stop_reason="failed",
                    ended_at=datetime.now(UTC),
                )
            )
            session.commit()


def _rows(session: Session, model: Any, *conds: Any) -> list[dict[str, Any]]:
    cols = [c.name for c in model.__table__.columns if not c.computed]
    return [
        dict(r._mapping) for r in session.execute(select(*[model.__table__.c[c] for c in cols]).where(*conds))
    ]


class ManualRunner:
    def __init__(self, session: Session, chat_llm: Any = None, json_llm: Any = None) -> None:
        self.session = session
        self.chat_llm = chat_llm
        self.json_llm = json_llm

    def _context(self, root: AgentRun, scope_run_id: UUID | None) -> Any:
        from app.agents.base import RunContext, RunParams
        from app.domain.models.master import Store
        from app.domain.schemas.ingestion import ValidationReport
        from app.services.ingestion_service import DataIngestionService
        from app.services.pos_source import SyntheticPosSource

        store_ids = list(self.session.scalars(select(Store.store_id)))
        report = ValidationReport()
        latest_day = self.session.scalar(text("SELECT max(snapshot_date) FROM inventory_daily_snapshot"))
        if latest_day is not None:
            svc = DataIngestionService(self.session, SyntheticPosSource())
            stale = svc._get_stale_days()
            for sid in store_ids:
                svc._flag_stale(sid, latest_day, stale, report)
        from app.domain.repositories.observability_repo import AgentRunLogger

        ctx = RunContext(
            run_id=root.run_id,
            run_date=root.run_date or date.today(),
            store_ids=store_ids,
            stale_skus=report.stale_skus,
            params=RunParams.load(self.session),
            logger=AgentRunLogger(self.session),
            session=self.session,
        )
        ctx.extra["mode"] = root.mode
        ctx.extra["scope_run_id"] = scope_run_id or root.run_id
        snap = snapshot(self.session)
        ctx.extra["llm_enabled"] = snap.llm_enabled
        if snap.llm_enabled:
            from app.agents.llm.agents import make_chat_llm, make_json_llm

            ctx.extra["chat_llm"] = self.chat_llm if self.chat_llm is not None else make_chat_llm()
            ctx.extra["json_llm"] = self.json_llm if self.json_llm is not None else make_json_llm()
        return ctx

    def _copy_upstream(self, agent_key: str, source: UUID, target: UUID) -> int:
        n = 0
        for table, cols in COPYABLE[agent_key]:
            extra_cols, extra_vals = (
                ("rule_id, ", "gen_random_uuid(), ") if table == "association_rule" else ("", "")
            )
            res = self.session.execute(
                text(
                    f"INSERT INTO {table} ({extra_cols}run_id, {cols}) SELECT {extra_vals}:target, {cols} "
                    f"FROM {table} WHERE run_id = :source"
                ),
                {"target": target, "source": source},
            )
            n += int(getattr(res, "rowcount", 0) or 0)
        return n

    def _supersede_for(self, agents: list[str]) -> dict[str, int]:
        from app.services.agent_decision_service import mark_superseded

        recs = select(AgentDecision.rec_id).where(
            AgentDecision.agent_key.in_(agents), AgentDecision.mode == "LIVE"
        )
        r1 = self.session.execute(
            update(Recommendation)
            .where(Recommendation.status == RecStatus.PENDING.value, Recommendation.rec_id.in_(recs))
            .values(status=RecStatus.SUPERSEDED.value)
        )
        r2 = self.session.execute(
            update(TransferOrder)
            .where(
                TransferOrder.status == TransferStatus.PROPOSED.value, TransferOrder.source_rec_id.in_(recs)
            )
            .values(status=TransferStatus.SUPERSEDED.value)
        )
        pos = 0
        if "purchase_order" in agents:
            decided = select(POLine.po_id).where(POLine.line_status.in_(["APPROVED", "EDITED", "REJECTED"]))
            ids = list(
                self.session.scalars(
                    select(PurchaseOrder.po_id).where(
                        PurchaseOrder.status == POStatus.PENDING_L1.value, PurchaseOrder.po_id.not_in(decided)
                    )
                )
            )
            if ids:
                self.session.execute(
                    update(PurchaseOrder)
                    .where(PurchaseOrder.po_id.in_(ids))
                    .values(status=POStatus.SUPERSEDED.value)
                )
                self.session.execute(
                    update(POLine)
                    .where(POLine.po_id.in_(ids), POLine.line_status == LineStatus.PENDING.value)
                    .values(line_status=LineStatus.SUPERSEDED.value)
                )
            pos = len(ids)
        mark_superseded(self.session)
        return {
            "recommendations": int(getattr(r1, "rowcount", 0) or 0),
            "transfers": int(getattr(r2, "rowcount", 0) or 0),
            "purchase_orders": pos,
        }

    def _collect_previews(self, root: AgentRun, key: str) -> list[dict[str, Any]]:
        rid = root.run_id
        out: list[dict[str, Any]] = []
        from app.domain.models.master import Product, Store

        names = dict(self.session.execute(select(Store.store_id, Store.name)).all())
        recs = self.session.execute(
            select(Recommendation, Product.name)
            .join(Product, Product.product_id == Recommendation.product_id)
            .where(Recommendation.run_id == rid)
        ).all()
        for r, pname in recs[:300]:
            out.append(
                {
                    "agent_key": key,
                    "output_type": "RECOMMENDATION",
                    "payload": {
                        "rec_type": r.rec_type,
                        "status": r.status,
                        "store": names.get(r.store_id),
                        "product": pname,
                        "qty": r.qty,
                        "priority": r.priority,
                        "explanation": r.explanation,
                        "evidence_kind": (r.evidence or {}).get("kind"),
                    },
                }
            )
        for n in self.session.scalars(
            select(ReplenishmentNeed).where(ReplenishmentNeed.run_id == rid).limit(200)
        ):
            out.append(
                {
                    "agent_key": key,
                    "output_type": "REPLENISHMENT_NEED",
                    "payload": {
                        "store": names.get(n.store_id),
                        "product_id": str(n.product_id),
                        "qty": n.qty,
                        "reason": n.reason,
                    },
                }
            )
        for t in self.session.scalars(
            select(TransferOrder).where(
                TransferOrder.source_rec_id.in_(
                    select(Recommendation.rec_id).where(Recommendation.run_id == rid)
                )
            )
        ):
            out.append(
                {
                    "agent_key": key,
                    "output_type": "TRANSFER",
                    "payload": {
                        "from": names.get(t.from_store_id),
                        "to": names.get(t.to_store_id),
                        "qty": t.qty,
                        "status": t.status,
                    },
                }
            )
        for po in self.session.scalars(select(PurchaseOrder).where(PurchaseOrder.run_id == rid)):
            lines = self.session.execute(
                select(POLine.store_id, POLine.qty).where(POLine.po_id == po.po_id)
            ).all()
            out.append(
                {
                    "agent_key": key,
                    "output_type": "PURCHASE_ORDER",
                    "payload": {"status": po.status, "lines": len(lines), "units": sum(q for _, q in lines)},
                }
            )
        for d in self.session.scalars(select(AgentDraft).where(AgentDraft.run_id == rid)):
            out.append(
                {
                    "agent_key": d.agent_key,
                    "output_type": d.draft_type,
                    "payload": {
                        "store": names.get(d.store_id) if d.store_id else None,
                        "qty": d.qty,
                        **(d.payload or {}),
                    },
                }
            )
        for rv in self.session.scalars(
            select(RecommendationReview).where(RecommendationReview.run_id == rid)
        ):
            if rv.verdict == "FLAGGED":
                out.append(
                    {
                        "agent_key": "recommendation_reviewer",
                        "output_type": "REVIEW_FLAG",
                        "payload": {"rec_id": str(rv.rec_id), "issues": rv.issues},
                    }
                )
        return out

    def execute(self, run_id: UUID) -> None:
        from app.agents.orchestrator import WorkflowOrchestrator
        from app.services.agent_decision_service import (
            mark_inputs_missing,
            record_decision,
            record_stage_decisions,
        )

        root = self.session.get(AgentRun, run_id)
        if root is None or root.status != "RUNNING" or not root.agent_key:
            return
        key, mode = root.agent_key, root.mode
        spec = BY_KEY[key]
        plan = root.input_ref or {}
        source = UUID(plan["source_run_id"]) if plan.get("source_run_id") else None
        t0 = time.monotonic()
        ctx = self._context(root, source if spec.kind == "LLM" else None)
        orch = WorkflowOrchestrator(
            self.session, chat_llm=ctx.extra.get("chat_llm"), json_llm=ctx.extra.get("json_llm")
        )
        logger_ = ctx.logger
        nested = self.session.begin_nested() if mode == "DRY_RUN" else None
        outcome: dict[str, str] = {}
        notes: dict[str, Any] = {}
        cancelled = False
        try:
            if spec.group == "PIPELINE":
                reruns: list[str] = []
                for u in plan.get("upstream", []):
                    if u["action"] == "REUSE" and source is not None and u["agent_key"] in COPYABLE:
                        n = self._copy_upstream(u["agent_key"], source, root.run_id)
                        logger_.log_tool_call(
                            root.run_id,
                            "reuse_upstream",
                            {"agent_key": u["agent_key"], "source_run_id": str(source)},
                            f"{n} rows copied",
                            0,
                            "OK",
                        )
                        outcome[u["agent_key"]] = "SUCCESS"
                    elif u["action"] == "RERUN":
                        reruns.append(u["agent_key"])
                chain = [k for k in PIPELINE_KEYS if k in set(reruns)] + [key]
                if mode == "LIVE":
                    chain += [d for d in plan.get("downstream", []) if d not in chain]
                    notes["superseded"] = self._supersede_for(chain)
                    logger_.log_tool_call(
                        root.run_id, "supersede_for", {"agents": chain}, notes["superseded"], 0, "OK"
                    )
                for k in chain:
                    if self._cancelled(run_id):
                        cancelled = True
                        break
                    missing = [d for d in BY_KEY[k].depends_on if outcome.get(d) != "SUCCESS"]
                    if missing:
                        orch._skip(
                            root.run_id,
                            k,
                            "SKIPPED_DEPENDENCY",
                            f"upstream did not run: {', '.join(missing)}",
                            ctx.summary(),
                        )
                        outcome[k] = "SKIPPED_DEPENDENCY"
                        continue
                    res = orch.run_stage(k, ctx, root.run_id, trigger_type=root.trigger_type, mode=mode)
                    outcome[k] = res.status
                    if res.status == "SUCCESS":
                        record_stage_decisions(self.session, root.run_id, k, mode)
                        absent = [o for o in BY_KEY[k].optional_inputs if outcome.get(o) != "SUCCESS"]
                        if absent and k == "stock_balancing":
                            mark_inputs_missing(self.session, root.run_id, absent)
                        logger_.store_stats(orch.last_child_run_id)
                    if mode == "LIVE":
                        self.session.commit()
            else:
                res = orch.run_stage(key, ctx, root.run_id, trigger_type=root.trigger_type, mode=mode)
                outcome[key] = res.status
                if key == "run_coordinator" and res.status == "SUCCESS":
                    for a in ctx.extra.get("coordinator_actions", []):
                        record_decision(
                            self.session,
                            run_id=root.run_id,
                            agent_key="run_coordinator",
                            decision_type="COORDINATOR_NO_ACTION"
                            if a.action == "NO_ACTION"
                            else "COORDINATOR_ESCALATE"
                            if a.action == "ESCALATE"
                            else "COORDINATOR_RETRY"
                            if a.action == "RETRY_AGENT"
                            else "COORDINATOR_MARK_PARTIAL"
                            if a.action == "MARK_PARTIAL"
                            else "COORDINATOR_INVOKE",
                            mode=mode,
                            summary=f"(planned, manual run) {a.action}: {a.reason}",
                            evidence_ref={"action": a.model_dump()},
                        )
            self.session.flush()
            if nested is not None:
                previews = self._collect_previews(root, key)
                decisions = _rows(self.session, AgentDecision, AgentDecision.run_id == root.run_id)
                children = _rows(self.session, AgentRun, AgentRun.parent_run_id == root.run_id)
                child_ids = [c["run_id"] for c in children]
                tool_rows = _rows(self.session, ToolCall, ToolCall.run_id.in_([*child_ids, root.run_id]))
                llm_rows = _rows(self.session, LLMUsage, LLMUsage.run_id.in_(child_ids or [root.run_id]))
                nested.rollback()
                nested = None
                # keep the run logs; outputs survive only as previews; decisions lose their output links
                if children:
                    self.session.execute(insert(AgentRun), children)
                if tool_rows:
                    self.session.execute(insert(ToolCall), tool_rows)
                if llm_rows:
                    self.session.execute(insert(LLMUsage), llm_rows)
                for p in previews:
                    self.session.add(AgentPreviewOutput(run_id=root.run_id, **p))
                for d in decisions:
                    d.update(
                        mode="DRY_RUN",
                        rec_id=None,
                        transfer_id=None,
                        po_id=None,
                        draft_id=None,
                        outcome="NOT_APPLICABLE",
                    )
                if decisions:
                    self.session.execute(insert(AgentDecision), decisions)
                notes["previews"] = len(previews)
            else:
                self._after_live()
        except Exception:
            if nested is not None:
                nested.rollback()
            raise
        statuses = set(outcome.values())
        final = (
            "CANCELLED"
            if cancelled
            else "FAILED"
            if outcome.get(key) == "FAILED"
            else "PARTIAL"
            if "FAILED" in statuses
            else "SUCCESS"
        )
        root = self.session.get(AgentRun, run_id)
        assert root is not None
        root.status = final
        root.ended_at = datetime.now(UTC)
        root.stop_reason = "cancelled by Super Admin" if cancelled else "completed"
        import json as _json

        root.output_summary = _json.dumps(
            {"stages": outcome, **notes, "duration_s": round(time.monotonic() - t0, 2)}, default=str
        )
        self.session.flush()
        logger_.store_stats(run_id)
        self.session.commit()

    def _cancelled(self, run_id: UUID) -> bool:
        return bool(self.session.scalar(select(AgentRun.cancel_requested).where(AgentRun.run_id == run_id)))

    def _after_live(self) -> None:
        try:
            self.session.execute(text("REFRESH MATERIALIZED VIEW mv_dashboard_store_day"))
            self.session.execute(text("REFRESH MATERIALIZED VIEW mv_inbox_counts"))
        except Exception as e:  # pragma: no cover - views optional in some test schemas
            logger.warning("view refresh failed: %s", e)
        try:
            from app.domain.models.master import Store
            from app.services.cache_service import CacheService

            cs = CacheService()
            # a live run changes the inbox, POs, transfers and dashboards of every store: drop their cached views
            stores = list(self.session.scalars(select(Store.store_id)))
            cs.invalidate_store_keys(stores, ["inbox", "dash", "inv", "twin"])
            prev = cs.get_latest_run_id()
            if prev:
                cs.invalidate_run(prev)
        except Exception as e:  # cache is best effort (cache-aside)
            logger.warning("cache invalidation failed: %s", e)
