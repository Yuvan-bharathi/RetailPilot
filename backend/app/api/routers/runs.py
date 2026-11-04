"""Pipeline runs and observability routes (spec §5, SD-01)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DbSession, RequireSuperAdmin
from app.core.errors import NotFound
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun, LLMUsage, ToolCall
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


class ToolCallDTO(BaseModel):
    tool_call_id: UUID
    tool_name: str
    args: dict[str, Any]
    duration_ms: int
    status: str
    created_at: datetime


class LLMUsageDTO(BaseModel):
    usage_id: UUID
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


class AgentRunDetailDTO(BaseModel):
    run_id: UUID
    parent_run_id: UUID | None
    agent_name: str
    run_date: date | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    input_ref: dict[str, Any]
    output_summary: str | None
    error: str | None
    tool_calls: list[ToolCallDTO] = Field(default_factory=list)
    llm_usages: list[LLMUsageDTO] = Field(default_factory=list)


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


@router.get("/agent-runs", response_model=list[AgentRunDetailDTO])
async def list_agent_runs(
    current_user: RequireSuperAdmin,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AgentRunDetailDTO]:
    """Returns recent agent runs for system observability."""
    stmt = select(AgentRun).order_by(desc(AgentRun.started_at)).limit(limit)
    result = await session.execute(stmt)
    runs = result.scalars().all()
    return [
        AgentRunDetailDTO(
            run_id=r.run_id,
            parent_run_id=r.parent_run_id,
            agent_name=r.agent_name,
            run_date=r.run_date,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.ended_at,
            input_ref=r.input_ref or {},
            output_summary=r.output_summary,
            error=r.error,
        )
        for r in runs
    ]


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetailDTO)
async def get_agent_run(
    run_id: UUID,
    current_user: RequireSuperAdmin,
    session: DbSession,
) -> AgentRunDetailDTO:
    """Returns detailed trace of a specific agent run including its tool calls and LLM usage."""
    stmt = select(AgentRun).where(AgentRun.run_id == run_id)
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise NotFound(f"Agent run {run_id} not found")

    tc_stmt = select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at)
    tc_res = await session.execute(tc_stmt)
    tool_calls = [
        ToolCallDTO(
            tool_call_id=tc.call_id,
            tool_name=tc.tool_name,
            args=tc.args or {},
            duration_ms=tc.duration_ms,
            status=tc.status,
            created_at=tc.created_at,
        )
        for tc in tc_res.scalars().all()
    ]

    llm_stmt = select(LLMUsage).where(LLMUsage.run_id == run_id).order_by(LLMUsage.created_at)
    llm_res = await session.execute(llm_stmt)
    llm_usages = [
        LLMUsageDTO(
            usage_id=u.usage_id,
            provider=u.provider,
            model=u.model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            created_at=u.created_at,
        )
        for u in llm_res.scalars().all()
    ]

    return AgentRunDetailDTO(
        run_id=run.run_id,
        parent_run_id=run.parent_run_id,
        agent_name=run.agent_name,
        run_date=run.run_date,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.ended_at,
        input_ref=run.input_ref or {},
        output_summary=run.output_summary,
        error=run.error,
        tool_calls=tool_calls,
        llm_usages=llm_usages,
    )
