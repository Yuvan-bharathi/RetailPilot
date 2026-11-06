"""Nightly Workflow Orchestrator (SD-01, decisions D-01, D-03, D-35).

Coordinates the end-to-end nightly replenishment pipeline:
1. Ingestion and POS validation (SD-02)
2. Run supersession (D-03)
3. Stages in order (D-50): Data Quality (LLM), the 6 replenishment agents, Recommendation Reviewer (LLM); then the
   Run Coordinator (LLM) on exceptions. Config snapshot at start; disabled → SKIPPED_DISABLED; a critical agent off
   → PAUSED; cancel honoured between stages; each stage's outputs are logged as decisions
4. Concurrent materialized view refresh (mv_dashboard_store_day, mv_inbox_counts)
5. Cache warming and previous run key invalidation
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.agents.base import AgentResult, BaseAgent, RunContext, RunParams
from app.agents.forecasting import DemandForecastingAgent
from app.agents.freshness import FreshnessAgent
from app.agents.purchase_order import PurchaseOrderAgent
from app.agents.registry import BY_KEY, PIPELINE_KEYS
from app.agents.related_products import RelatedProductAgent
from app.agents.sales_analytics import SalesAnalyticsAgent
from app.agents.stock_balancing import StockBalancingAgent
from app.domain.models.enums import LineStatus, POStatus, RecStatus, TransferStatus
from app.domain.models.master import Store
from app.domain.models.observability import AgentRun
from app.domain.models.planning import Recommendation
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.transfers import TransferOrder
from app.domain.repositories.observability_repo import AgentRunLogger
from app.domain.schemas.ingestion import ValidationReport
from app.services.cache_service import CacheService
from app.services.ingestion_service import DataIngestionService
from app.services.pos_source import PosSource, SyntheticPosSource

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: UUID
    status: str
    recommendations_count: int = 0
    po_count: int = 0
    transfers_count: int = 0
    duration_s: float = 0.0
    error: str | None = None
    validation_report: ValidationReport | None = None


class RunSupersession:
    @staticmethod
    def supersede_previous(session: Session, current_run_id: UUID) -> dict[str, int]:
        """Supersedes unacted items from earlier runs (D-03).

        - PENDING recommendations -> SUPERSEDED
        - PROPOSED transfers linked to superseded recs -> SUPERSEDED
        - PENDING_L1 POs where NO line has been decided -> SUPERSEDED
        """
        # 1. Supersede previous PENDING recommendations
        rec_stmt = (
            update(Recommendation)
            .where(
                Recommendation.status == RecStatus.PENDING.value,
                Recommendation.run_id != current_run_id,
            )
            .values(status=RecStatus.SUPERSEDED.value)
        )
        rec_res = session.execute(rec_stmt)
        recs_superseded = int(getattr(rec_res, "rowcount", 0) or 0)

        # 2. Supersede previous PROPOSED transfers
        # Join against recommendation via source_rec_id
        tr_subq = (
            select(Recommendation.rec_id).where(Recommendation.run_id != current_run_id).scalar_subquery()
        )
        tr_stmt = (
            update(TransferOrder)
            .where(
                TransferOrder.status == TransferStatus.PROPOSED.value,
                TransferOrder.source_rec_id.in_(tr_subq),
            )
            .values(status=TransferStatus.SUPERSEDED.value)
        )
        tr_res = session.execute(tr_stmt)
        transfers_superseded = int(getattr(tr_res, "rowcount", 0) or 0)

        # 3. Supersede undecided PENDING_L1 POs
        undecided_pos_stmt = select(PurchaseOrder.po_id).where(
            PurchaseOrder.status == POStatus.PENDING_L1.value,
            PurchaseOrder.run_id != current_run_id,
        )
        candidate_po_ids = list(session.scalars(undecided_pos_stmt).all())
        pos_superseded = 0

        for po_id in candidate_po_ids:
            # Check if any line has been decided (APPROVED, EDITED, REJECTED)
            decided_count = session.scalar(
                select(POLine.po_line_id)
                .where(
                    POLine.po_id == po_id,
                    POLine.line_status.in_(
                        [
                            LineStatus.APPROVED.value,
                            LineStatus.EDITED.value,
                            LineStatus.REJECTED.value,
                        ]
                    ),
                )
                .limit(1)
            )
            if decided_count is None:
                # Undecided PO: supersede entire PO and all lines
                session.execute(
                    update(PurchaseOrder)
                    .where(PurchaseOrder.po_id == po_id)
                    .values(status=POStatus.SUPERSEDED.value)
                )
                session.execute(
                    update(POLine)
                    .where(POLine.po_id == po_id, POLine.line_status == LineStatus.PENDING.value)
                    .values(line_status=LineStatus.SUPERSEDED.value)
                )
                pos_superseded += 1

        session.flush()
        return {
            "recommendations": recs_superseded,
            "transfers": transfers_superseded,
            "purchase_orders": pos_superseded,
        }


def next_run_date(session: Session) -> date:
    """The day after the latest POS day loaded (a run plans the next day); today if nothing is loaded."""
    latest = session.scalar(text("SELECT max(snapshot_date) FROM inventory_daily_snapshot"))
    return latest + timedelta(days=1) if latest else date.today()


#: Nightly stage order (D-50): Objective III Data Quality after ingestion, the six deterministic stages, the
#: Recommendation Reviewer before the inbox; the Run Coordinator runs last on exceptions.
STAGES: tuple[str, ...] = (
    "data_quality",
    "sales_analytics",
    "demand_forecasting",
    "related_product",
    "stock_balancing",
    "freshness",
    "purchase_order",
    "recommendation_reviewer",
)
#: stages allowed to run while replenishment is paused (they create no inbox items)
_RUN_WHILE_PAUSED = frozenset({"data_quality", "sales_analytics"})
_STALE_RUNNING_HOURS = 6


def agent_class(agent_key: str) -> type[BaseAgent]:
    from app.agents.llm.agents import LLM_AGENT_CLASSES

    spec = BY_KEY[agent_key]
    if spec.kind == "LLM":
        return LLM_AGENT_CLASSES[agent_key]
    return {cls.name: cls for cls in WorkflowOrchestrator.AGENT_SEQUENCE}[spec.class_name or ""]


class WorkflowOrchestrator:
    AGENT_SEQUENCE: Sequence[type[BaseAgent]] = (
        SalesAnalyticsAgent,
        DemandForecastingAgent,
        RelatedProductAgent,
        StockBalancingAgent,
        FreshnessAgent,
        PurchaseOrderAgent,
    )

    def __init__(
        self,
        session: Session,
        pos_source: PosSource | None = None,
        cache_service: CacheService | None = None,
        *,
        commit_per_stage: bool = False,
        chat_llm: Any = None,
        json_llm: Any = None,
        agent_overrides: dict[str, type[BaseAgent]] | None = None,
    ) -> None:
        """`commit_per_stage` (Celery, scripts, manual live triggers): commit after each stage so the console sees
        RUNNING runs and stage progress and a cancel request can be honoured. Outputs of finished stages were already
        committed on failure (callers commit a FAILED run, D-47), so the semantics do not change.
        `chat_llm` / `json_llm`: inject a model (tests, evals); default: the configured Groq client when the global
        LLM switch is on, else the agents' deterministic baselines."""
        self.session = session
        self.pos_source = pos_source or SyntheticPosSource()
        self.cache_service = cache_service or CacheService()
        self.logger = AgentRunLogger(session)
        self.commit_per_stage = commit_per_stage
        self._chat_llm = chat_llm
        self._json_llm = json_llm
        self.agent_overrides = agent_overrides or {}

    # --- helpers --------------------------------------------------------------------------------------------------

    def _commit(self) -> None:
        if self.commit_per_stage:
            self.session.commit()

    def _cancel_requested(self, run_id: UUID) -> bool:
        return bool(self.session.scalar(select(AgentRun.cancel_requested).where(AgentRun.run_id == run_id)))

    def _abandon_stale_runs(self) -> None:
        """A crashed process leaves a committed RUNNING row that would block the date (D-35 index)."""
        cutoff = datetime.now(UTC) - timedelta(hours=_STALE_RUNNING_HOURS)
        self.session.execute(
            update(AgentRun)
            .where(AgentRun.status == "RUNNING", AgentRun.started_at < cutoff)
            .values(
                status="FAILED",
                error="Abandoned: no progress for 6 hours",
                stop_reason="abandoned",
                ended_at=datetime.now(UTC),
            )
        )

    def _skip(self, root: UUID, key: str, status: str, reason: str, ctx_summary: dict[str, Any]) -> None:
        spec = BY_KEY[key]
        child = self.logger.start_run(
            agent_name=spec.class_name or spec.name,
            parent_run_id=root,
            input_ref=ctx_summary,
            agent_key=key,
            trigger_type="NIGHTLY",
        )
        self.logger.finish_run(child, status=status, stop_reason=reason)

    def run_stage(
        self,
        key: str,
        ctx: RunContext,
        parent_run_id: UUID,
        *,
        attempt_offset: int = 0,
        trigger_type: str = "NIGHTLY",
        mode: str = "LIVE",
    ) -> AgentResult:
        """Run one registered agent as a child run with the SD-01 retry policy (2 attempts)."""
        spec = BY_KEY[key]
        agent = self.agent_overrides.get(key, agent_class(key))()
        child_run_id = self.logger.start_run(
            agent_name=agent.name,
            parent_run_id=parent_run_id,
            input_ref=ctx.summary(),
            agent_key=key,
            trigger_type=trigger_type,
            mode=mode,
        )
        child_ctx = ctx.with_run(child_run_id)
        result: AgentResult | None = None
        attempts = 0
        for attempt in range(1, 3):
            attempts = attempt
            try:
                result = agent.run(child_ctx)
                if result.status == "SUCCESS":
                    break
                if result.step_count > ctx.params.max_steps:
                    result = AgentResult(
                        status="FAILED",
                        step_count=result.step_count,
                        error=f"Step limit exceeded ({result.step_count} > {ctx.params.max_steps})",
                    )
                    break
            except Exception as e:
                logger.exception("Agent %s failed on attempt %d: %s", agent.name, attempt, e)
                if attempt < 2:
                    time.sleep(0.5 * attempt)
                else:
                    result = AgentResult(
                        status="FAILED", error=f"{type(e).__name__}: {e}", step_count=attempt
                    )
        retries = attempts - 1 + attempt_offset
        if result is None or result.status != "SUCCESS":
            err = result.error if result else "Unknown execution error"
            self.logger.finish_run(
                child_run_id,
                status="FAILED",
                output_summary=result.outputs if result else {},
                error=err,
                stop_reason="failed",
                retries=retries,
            )
            return result or AgentResult(status="FAILED", error=err)
        stop = str(result.outputs.get("stop_reason", "completed")) if spec.kind == "LLM" else "completed"
        self.logger.finish_run(
            child_run_id, status="SUCCESS", output_summary=result.outputs, stop_reason=stop, retries=retries
        )
        return result

    # --- nightly --------------------------------------------------------------------------------------------------

    def run_nightly(
        self,
        run_id: UUID | None = None,
        run_date: date | None = None,
    ) -> RunSummary:
        from app.services.agent_config_service import snapshot, sync_registry
        from app.services.agent_decision_service import mark_superseded, record_stage_decisions

        start_time = time.monotonic()
        if run_id is None:
            run_id = uuid.uuid4()
        if run_date is None:
            run_date = date.today()

        if self.commit_per_stage:
            self._abandon_stale_runs()
        # Idempotency check: is a run already running for this run_date?
        existing_running = self.session.scalar(
            select(AgentRun.run_id).where(
                AgentRun.agent_name == "nightly",
                AgentRun.run_date == run_date,
                AgentRun.status == "RUNNING",
            )
        )
        if existing_running and existing_running != run_id:
            logger.warning("Nightly run %s already running for date %s", existing_running, run_date)
            return RunSummary(
                run_id=existing_running,
                status="ALREADY_RUNNING",
                error=f"Run {existing_running} is already in progress",
            )

        # 0. Registry + configuration snapshot: toggles apply from the NEXT run (docs/09 §4)
        sync_registry(self.session)
        config = snapshot(self.session)

        # 1. Start root nightly run
        self.logger.start_run(
            agent_name="nightly",
            parent_run_id=None,
            input_ref={"run_date": run_date.isoformat(), "run_id": str(run_id)},
            run_id=run_id,
            run_date=run_date,
            trigger_type="NIGHTLY",
            config_version=config.version,
            config_snapshot=config.as_json(),
        )
        self._commit()

        # 2. Get active store IDs
        store_ids = list(self.session.scalars(select(Store.store_id)).all())
        if not store_ids:
            err = "No stores found in database"
            self.logger.finish_run(run_id, status="FAILED", error=err, stop_reason="no stores")
            return RunSummary(run_id=run_id, status="FAILED", error=err)

        # 3. Data Ingestion & Validation (SD-02)
        ingestion_service = DataIngestionService(self.session, self.pos_source)
        # The run plans `run_date`; the POS data to ingest is the previous business day (history ends there).
        report = ingestion_service.load_and_validate(
            run_date=run_date - timedelta(days=1), store_ids=store_ids
        )
        self.session.flush()

        # A critical pipeline agent switched off → replenishment PAUSED: previous results stay, nothing superseded
        paused_by = [k for k in PIPELINE_KEYS if BY_KEY[k].critical and not config.is_on(k)]
        paused = bool(paused_by)

        # 4. Supersede previous runs (D-03)
        if not paused:
            superseded = RunSupersession.supersede_previous(self.session, run_id)
            mark_superseded(self.session)
            self.logger.log_tool_call(
                run_id=run_id,
                tool_name="supersede_previous",
                args={"run_id": str(run_id)},
                result_summary=superseded,
                duration_ms=0,
                status="OK",
            )
        self._commit()

        # 5. Initialize context
        params = RunParams.load(self.session)
        ctx = RunContext(
            run_id=run_id,
            run_date=run_date,
            store_ids=store_ids,
            stale_skus=report.stale_skus,
            params=params,
            logger=self.logger,
            session=self.session,
        )
        ctx.extra["mode"] = "LIVE"
        ctx.extra["scope_run_id"] = run_id
        ctx.extra["llm_enabled"] = config.llm_enabled
        if config.llm_enabled:
            from app.agents.llm.agents import make_chat_llm, make_json_llm

            ctx.extra["chat_llm"] = self._chat_llm if self._chat_llm is not None else make_chat_llm()
            ctx.extra["json_llm"] = self._json_llm if self._json_llm is not None else make_json_llm()

        overall_status = "SUCCESS"
        outcome: dict[str, str] = {}
        cancelled = False
        critical_failure: str | None = None

        # 6. Stages in order
        for key in STAGES:
            spec = BY_KEY[key]
            if cancelled or self._cancel_requested(run_id):
                cancelled = True
                break
            if critical_failure:
                self._skip(run_id, key, "SKIPPED_DEPENDENCY", f"stopped: {critical_failure}", ctx.summary())
                outcome[key] = "SKIPPED_DEPENDENCY"
                continue
            if not config.is_on(key):
                llm_off = spec.kind == "LLM" and not config.llm_enabled
                reason = "all LLM agents off" if llm_off else f"agent disabled (config v{config.version})"
                self._skip(run_id, key, "SKIPPED_DISABLED", reason, ctx.summary())
                outcome[key] = "SKIPPED_DISABLED"
                continue
            if paused and key not in _RUN_WHILE_PAUSED:
                self._skip(
                    run_id,
                    key,
                    "SKIPPED_DEPENDENCY",
                    f"replenishment paused: {', '.join(paused_by)} off",
                    ctx.summary(),
                )
                outcome[key] = "SKIPPED_DEPENDENCY"
                continue
            missing = [d for d in spec.depends_on if outcome.get(d) != "SUCCESS"]
            if missing:
                self._skip(
                    run_id,
                    key,
                    "SKIPPED_DEPENDENCY",
                    f"upstream did not run: {', '.join(missing)}",
                    ctx.summary(),
                )
                outcome[key] = "SKIPPED_DEPENDENCY"
                continue
            absent = [o for o in spec.optional_inputs if outcome.get(o) != "SUCCESS"]
            if absent:  # e.g. related products off → stock balancing runs without co-replenishment, says so
                self.logger.log_tool_call(
                    run_id=run_id,
                    tool_name="input_missing",
                    args={"agent_key": key, "missing": absent},
                    result_summary=f"{spec.name} runs without: {', '.join(absent)}",
                    duration_ms=0,
                    status="WARN",
                )
            result = self.run_stage(key, ctx, run_id)
            outcome[key] = result.status
            if result.status == "SUCCESS":
                record_stage_decisions(self.session, run_id, key)
            elif spec.critical:
                critical_failure = f"Critical agent {spec.class_name or spec.name} failed: {result.error}"
                overall_status = "FAILED"
            else:
                overall_status = "PARTIAL"
            self.session.flush()
            self._commit()

        # 7. Run Coordinator on exceptions (allow-listed recovery); off → deterministic SD-01 behaviour above
        escalations = 0
        if not cancelled and not paused and config.is_on("run_coordinator"):
            ctx.extra["coordinator_actions"] = []
            coord = self.run_stage("run_coordinator", ctx, run_id)
            outcome["run_coordinator"] = coord.status
            if coord.status == "SUCCESS":
                overall_status, escalations = self._execute_coordinator(
                    ctx, run_id, outcome, overall_status, config
                )
            self._commit()

        # 8. Flush database changes
        self.session.flush()

        if critical_failure or cancelled:
            status = "CANCELLED" if cancelled else "FAILED"
            self.logger.finish_run(
                run_id,
                status=status,
                error=critical_failure,
                stop_reason="cancelled by Super Admin" if cancelled else "critical stage failed",
                output_summary={"stages": outcome, "escalations": escalations},
            )
            self.session.flush()
            self._commit()
            return RunSummary(
                run_id=run_id,
                status=status,
                error=critical_failure or "cancelled",
                duration_s=time.monotonic() - start_time,
                validation_report=report,
            )

        # 9. Refresh materialized views
        try:
            self.session.execute(text("REFRESH MATERIALIZED VIEW mv_dashboard_store_day"))
            self.session.execute(text("REFRESH MATERIALIZED VIEW mv_inbox_counts"))
            self.session.flush()
        except Exception as e:
            logger.warning("Materialized view refresh skipped/failed: %s", e)

        # 10. Update Redis cache keys and invalidate old run (not when paused: users keep the last results)
        if not paused:
            prev_run_id = self.cache_service.get_latest_run_id()
            self.cache_service.set_latest_run_id(run_id)
            self.cache_service.warm(run_id, store_ids)
            if prev_run_id and prev_run_id != run_id:
                self.cache_service.invalidate_run(prev_run_id)

        # 11. Finish root run
        duration_s = time.monotonic() - start_time
        recs_count = (
            self.session.scalar(
                select(text("COUNT(*)")).select_from(Recommendation).where(Recommendation.run_id == run_id)
            )
            or 0
        )
        po_count = (
            self.session.scalar(
                select(text("COUNT(*)")).select_from(PurchaseOrder).where(PurchaseOrder.run_id == run_id)
            )
            or 0
        )
        transfers_count = self.session.scalar(select(text("COUNT(*)")).select_from(TransferOrder)) or 0
        final_status = "PAUSED" if paused else overall_status
        summary_dict = {
            "recommendations": recs_count,
            "purchase_orders": po_count,
            "duration_s": round(duration_s, 2),
            "status": final_status,
            "stages": outcome,
            "escalations": escalations,
        }
        self.logger.finish_run(
            run_id,
            status=final_status,
            output_summary=summary_dict,
            stop_reason=(
                f"replenishment paused: {', '.join(paused_by)} off"
                if paused
                else "completed"
                if final_status == "SUCCESS"
                else "completed with partial results"
            ),
        )
        self.session.flush()
        self._commit()

        return RunSummary(
            run_id=run_id,
            status=final_status,
            recommendations_count=int(recs_count),
            po_count=int(po_count),
            transfers_count=int(transfers_count),
            duration_s=round(duration_s, 2),
            validation_report=report,
        )

    def _execute_coordinator(
        self, ctx: RunContext, run_id: UUID, outcome: dict[str, str], status: str, config: Any
    ) -> tuple[str, int]:
        """Execute the coordinator's accepted, allow-listed actions; each one is a decision row."""
        from app.domain.models.users import Notification
        from app.services.agent_decision_service import record_decision, record_stage_decisions

        escalations = 0
        for action in ctx.extra.get("coordinator_actions", []):
            name = action.action
            dtype = {
                "RETRY_AGENT": "COORDINATOR_RETRY",
                "ESCALATE": "COORDINATOR_ESCALATE",
                "MARK_PARTIAL": "COORDINATOR_MARK_PARTIAL",
                "NO_ACTION": "COORDINATOR_NO_ACTION",
            }.get(name, "COORDINATOR_INVOKE")
            summary = f"{name.replace('_', ' ').lower()}{' ' + action.agent_key if action.agent_key else ''}: {action.reason}"
            if name == "RETRY_AGENT" and action.agent_key:
                res = self.run_stage(action.agent_key, ctx, run_id, attempt_offset=1)
                outcome[action.agent_key] = res.status
                if res.status == "SUCCESS":
                    record_stage_decisions(self.session, run_id, action.agent_key)
                    if (
                        all(v in ("SUCCESS", "SKIPPED_DISABLED") for v in outcome.values())
                        and status == "PARTIAL"
                    ):
                        status = "SUCCESS"
                summary += f" → {res.status}"
            elif name == "MARK_PARTIAL":
                status = "PARTIAL" if status == "SUCCESS" else status
            elif name == "ESCALATE":
                escalations += 1
                self.session.add(
                    Notification(
                        role="SUPER_ADMIN",
                        message=f"Run {ctx.run_date}: {action.reason}"[:300],
                        link=f"/agents/logs/{run_id}",
                    )
                )
            elif name.startswith("INVOKE_"):
                key = {
                    "INVOKE_DATA_QUALITY": "data_quality",
                    "INVOKE_REPLENISHMENT_ACTION": "replenishment_action",
                    "INVOKE_REVIEWER": "recommendation_reviewer",
                }[name]
                if config.is_on(key):
                    res = self.run_stage(key, ctx, run_id, trigger_type="ON_DEMAND")
                    outcome[key] = res.status
                    summary += f" → {res.status}"
                else:
                    summary += " → skipped (agent disabled)"
            record_decision(
                self.session,
                run_id=run_id,
                agent_key="run_coordinator",
                decision_type=dtype,
                summary=summary,
                evidence_ref={"action": action.model_dump()},
            )
        return status, escalations
