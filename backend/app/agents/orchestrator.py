"""Nightly Workflow Orchestrator (SD-01, decisions D-01, D-03, D-35).

Coordinates the end-to-end nightly replenishment pipeline:
1. Ingestion and POS validation (SD-02)
2. Run supersession (D-03)
3. 6 replenishment agents in sequence with step cap and idempotency
4. Concurrent materialized view refresh (mv_dashboard_store_day, mv_inbox_counts)
5. Cache warming and previous run key invalidation
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.agents.base import AgentResult, BaseAgent, RunContext, RunParams
from app.agents.forecasting import DemandForecastingAgent
from app.agents.freshness import FreshnessAgent
from app.agents.purchase_order import PurchaseOrderAgent
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
    ) -> None:
        self.session = session
        self.pos_source = pos_source or SyntheticPosSource()
        self.cache_service = cache_service or CacheService()
        self.logger = AgentRunLogger(session)

    def run_nightly(
        self,
        run_id: UUID | None = None,
        run_date: date | None = None,
    ) -> RunSummary:
        start_time = time.monotonic()
        if run_id is None:
            run_id = uuid.uuid4()
        if run_date is None:
            run_date = date.today()

        # Idempotency check: is a run already running for this run_date?
        existing_running = self.session.scalar(
            select(AgentRun.run_id).where(
                AgentRun.agent_name == "nightly",
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

        # 1. Start root nightly run
        self.logger.start_run(
            agent_name="nightly",
            parent_run_id=None,
            input_ref={"run_date": run_date.isoformat(), "run_id": str(run_id)},
            run_id=run_id,
            run_date=run_date,
        )

        # 2. Get active store IDs
        store_ids = list(self.session.scalars(select(Store.store_id)).all())
        if not store_ids:
            err = "No stores found in database"
            self.logger.finish_run(run_id, status="FAILED", error=err)
            return RunSummary(run_id=run_id, status="FAILED", error=err)

        # 3. Data Ingestion & Validation (SD-02)
        ingestion_service = DataIngestionService(self.session, self.pos_source)
        report = ingestion_service.load_and_validate(run_date=run_date, store_ids=store_ids)
        self.session.flush()

        # 4. Supersede previous runs (D-03)
        superseded = RunSupersession.supersede_previous(self.session, run_id)
        self.logger.log_tool_call(
            run_id=run_id,
            tool_name="supersede_previous",
            args={"run_id": str(run_id)},
            result_summary=superseded,
            duration_ms=0,
            status="OK",
        )

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

        overall_status = "SUCCESS"
        max_retries = 2

        # 6. Run replenishment agents in sequence
        for agent_cls in self.AGENT_SEQUENCE:
            agent = agent_cls()
            child_run_id = self.logger.start_run(
                agent_name=agent.name,
                parent_run_id=run_id,
                input_ref=ctx.summary(),
            )
            child_ctx = ctx.with_run(child_run_id)

            agent_result: AgentResult | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    agent_result = agent.run(child_ctx)
                    if agent_result.status == "SUCCESS":
                        break
                    if agent_result.step_count > ctx.params.max_steps:
                        agent_result = AgentResult(
                            status="FAILED",
                            error=f"Step limit exceeded ({agent_result.step_count} > {ctx.params.max_steps})",
                            step_count=agent_result.step_count,
                        )
                        break
                except Exception as e:
                    logger.exception("Agent %s failed on attempt %d: %s", agent.name, attempt, e)
                    if attempt < max_retries:
                        time.sleep(0.5 * attempt)
                    else:
                        agent_result = AgentResult(status="FAILED", error=str(e), step_count=attempt)

            if agent_result is None or agent_result.status != "SUCCESS":
                err_msg = agent_result.error if agent_result else "Unknown execution error"
                self.logger.finish_run(
                    child_run_id,
                    status="FAILED",
                    output_summary=agent_result.outputs if agent_result else {},
                    error=err_msg,
                )
                if agent.critical:
                    # Critical agent failure terminates pipeline without cache swap
                    self.logger.finish_run(
                        run_id,
                        status="FAILED",
                        error=f"Critical agent {agent.name} failed: {err_msg}",
                    )
                    self.session.flush()
                    return RunSummary(
                        run_id=run_id,
                        status="FAILED",
                        error=f"Critical agent {agent.name} failed: {err_msg}",
                        duration_s=time.monotonic() - start_time,
                        validation_report=report,
                    )
                else:
                    overall_status = "PARTIAL"
            else:
                self.logger.finish_run(
                    child_run_id,
                    status=agent_result.status,
                    output_summary=agent_result.outputs,
                )

        # 7. Flush database changes
        self.session.flush()

        # 8. Refresh materialized views
        try:
            self.session.execute(text("REFRESH MATERIALIZED VIEW mv_dashboard_store_day"))
            self.session.execute(text("REFRESH MATERIALIZED VIEW mv_inbox_counts"))
            self.session.flush()
        except Exception as e:
            logger.warning("Materialized view refresh skipped/failed: %s", e)

        # 9. Update Redis cache keys and invalidate old run
        prev_run_id = self.cache_service.get_latest_run_id()
        self.cache_service.set_latest_run_id(run_id)
        self.cache_service.warm(run_id, store_ids)
        if prev_run_id and prev_run_id != run_id:
            self.cache_service.invalidate_run(prev_run_id)

        # 10. Finish root run
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

        summary_dict = {
            "recommendations": recs_count,
            "purchase_orders": po_count,
            "duration_s": round(duration_s, 2),
            "status": overall_status,
        }
        self.logger.finish_run(run_id, status=overall_status, output_summary=summary_dict)
        self.session.flush()

        return RunSummary(
            run_id=run_id,
            status=overall_status,
            recommendations_count=int(recs_count),
            po_count=int(po_count),
            transfers_count=int(transfers_count),
            duration_s=round(duration_s, 2),
            validation_report=report,
        )
