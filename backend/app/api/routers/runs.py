"""Pipeline run routes (spec §5, SD-01). Agent runs, traces and decisions: routers/agents.py (D-50)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DbSession, RequireSuperAdmin
from app.core.errors import NotFound
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun
from app.domain.schemas.dtos import RunInfoDTO

router = APIRouter(tags=["runs"])


class TriggerRunRequest(BaseModel):
    run_date: date | None = Field(
        default=None, description="Target run date; defaults to the day after the latest loaded POS day"
    )


class TriggerRunResponse(BaseModel):
    message: str
    run_id: str | None = None
    run_date: date | None = None


@router.get("/runs/latest", response_model=RunInfoDTO)
async def get_latest_run(current_user: CurrentUser, session: DbSession) -> RunInfoDTO:
    """Returns the latest successful nightly run for 'Data as of last run'."""
    stmt = (
        select(AgentRun)
        .where(
            AgentRun.agent_name == NIGHTLY_AGENT,
            AgentRun.status.in_(["SUCCESS", "PARTIAL"]),
        )
        .order_by(desc(AgentRun.ended_at), desc(AgentRun.started_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        # Fallback to the latest run of any status
        stmt_any = (
            select(AgentRun)
            .where(AgentRun.agent_name == NIGHTLY_AGENT)
            .order_by(desc(AgentRun.started_at))
            .limit(1)
        )
        result_any = await session.execute(stmt_any)
        run = result_any.scalar_one_or_none()

    if run is None:
        raise NotFound("No pipeline runs found")

    return RunInfoDTO(
        run_id=run.run_id,
        run_date=run.run_date or date.today(),
        status="SUCCESS" if run.status == "SUCCESS" else "PARTIAL",
        finished_at=run.ended_at or run.started_at or datetime.now(UTC),
    )


@router.post("/admin/runs", response_model=TriggerRunResponse)
async def trigger_nightly_run(
    body: TriggerRunRequest,
    _admin: RequireSuperAdmin,
) -> TriggerRunResponse:
    """Triggers the nightly replenishment pipeline manually (Super Admin only)."""
    from app.workers.tasks import nightly_run_task

    # No date → the worker plans the day after the latest loaded POS day (next_run_date)
    async_res = nightly_run_task.delay(str(body.run_date) if body.run_date else None)
    target_date = body.run_date
    return TriggerRunResponse(
        message=f"Nightly pipeline queued for {target_date or 'the next business day'}",
        run_id=str(async_res.id),
        run_date=target_date,
    )
