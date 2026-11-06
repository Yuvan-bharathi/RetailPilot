"""Agent console routes (docs/09 §5, D-50) — Super Admin only. Thin: validation + service calls."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api.deps import DbSession, RequireSuperAdmin
from app.domain.schemas.agents import (
    AgentDetailDTO,
    AgentListDTO,
    AgentRunItemDTO,
    AgentRunPage,
    AgentRunTraceDTO,
    AgentStatsDTO,
    DecisionPage,
    DecisionStatDTO,
    OutcomeT,
    PipelinePage,
    RunGraphDTO,
    RunModeT,
    RunStatusT,
    ToggleAgentRequest,
    ToggleLLMRequest,
    TriggerAgentRequest,
    TriggerPreviewDTO,
    TriggerResultDTO,
    TriggerTypeT,
)
from app.services.agent_config_service import AgentConfigService
from app.services.agent_console_service import AgentConsoleService
from app.services.agent_trigger_service import AgentTriggerService, run_trigger_in_background

router = APIRouter(tags=["agents"])

_console = AgentConsoleService()
_config = AgentConfigService()
_trigger = AgentTriggerService()

AgentKey = Annotated[str, "registry key"]
Cursor = Annotated[str | None, Query(max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
PageSize = Annotated[int, Query(ge=1, le=200)]


@router.get("/agents", response_model=AgentListDTO)
async def list_agents(_admin: RequireSuperAdmin, session: DbSession) -> AgentListDTO:
    return await _console.list_agents(session)


@router.patch("/agents/llm", response_model=AgentListDTO)
async def toggle_llm_agents(
    body: ToggleLLMRequest, admin: RequireSuperAdmin, session: DbSession
) -> AgentListDTO:
    """Global "All LLM agents" switch (cost and safety kill switch). Applies from the next run."""
    await _config.set_llm_enabled(session, body.enabled, body.reason, admin)
    return await _console.list_agents(session)


@router.get("/agents/{agent_key}", response_model=AgentDetailDTO)
async def get_agent(agent_key: AgentKey, _admin: RequireSuperAdmin, session: DbSession) -> AgentDetailDTO:
    return await _console.get_agent(session, agent_key)


@router.patch("/agents/{agent_key}", response_model=AgentDetailDTO)
async def toggle_agent(
    agent_key: AgentKey, body: ToggleAgentRequest, admin: RequireSuperAdmin, session: DbSession
) -> AgentDetailDTO:
    """Turn an agent on or off (reason required, audited, versioned). Applies from the NEXT run."""
    await _config.set_agent_enabled(
        session, agent_key, body.enabled, body.reason, admin, body.confirm_critical
    )
    return await _console.get_agent(session, agent_key)


@router.get("/agents/{agent_key}/stats", response_model=AgentStatsDTO)
async def agent_stats(
    agent_key: AgentKey,
    _admin: RequireSuperAdmin,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> AgentStatsDTO:
    return await _console.agent_stats(session, agent_key, days)


@router.get("/agents/{agent_key}/trigger-preview", response_model=TriggerPreviewDTO)
async def trigger_preview(
    agent_key: AgentKey, _admin: RequireSuperAdmin, session: DbSession, mode: RunModeT = "DRY_RUN"
) -> TriggerPreviewDTO:
    """What a "Run now" would do: upstream reuse / re-run, downstream re-runs, supersession, blocks."""
    return await _trigger.preview(session, agent_key, mode)


@router.post(
    "/agents/{agent_key}/runs", response_model=TriggerResultDTO, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_agent(
    agent_key: AgentKey,
    body: TriggerAgentRequest,
    admin: RequireSuperAdmin,
    session: DbSession,
    background: BackgroundTasks,
) -> TriggerResultDTO:
    """Run now. DRY_RUN (default) stores outputs in a preview set only; LIVE publishes like a nightly stage and
    needs a reason and confirmation. Runs in the background; poll GET /agent-runs/{run_id}."""
    result = await _trigger.start(session, agent_key, body, admin)
    background.add_task(run_trigger_in_background, result.run_id)
    return result


@router.get("/agent-runs", response_model=AgentRunPage)
async def list_agent_runs(
    _admin: RequireSuperAdmin,
    session: DbSession,
    cursor: Cursor = None,
    page_size: PageSize = 25,
    agent_key: str | None = None,
    status_: Annotated[RunStatusT | None, Query(alias="status")] = None,
    trigger_type: TriggerTypeT | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    roots_only: bool = False,
) -> AgentRunPage:
    """Agent runs, newest first (keyset paging)."""
    return await _console.list_runs(
        session,
        cursor=cursor,
        page_size=page_size,
        agent_key=agent_key,
        status=status_,
        trigger_type=trigger_type,
        date_from=date_from,
        date_to=date_to,
        roots_only=roots_only,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunTraceDTO)
async def get_agent_run(run_id: UUID, _admin: RequireSuperAdmin, session: DbSession) -> AgentRunTraceDTO:
    """Run trace: steps (tool calls, LLM calls, child runs, errors, stop reason), previews of a dry run."""
    return await _console.get_trace(session, run_id)


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRunItemDTO)
async def cancel_agent_run(run_id: UUID, admin: RequireSuperAdmin, session: DbSession) -> AgentRunItemDTO:
    """Request cancellation of a RUNNING root run; it stops after the current step."""
    return await _trigger.cancel(session, run_id, admin)


@router.get("/agent-decisions", response_model=DecisionPage)
async def list_decisions(
    _admin: RequireSuperAdmin,
    session: DbSession,
    cursor: Cursor = None,
    page_size: PageSize = 25,
    agent_key: str | None = None,
    decision_type: str | None = None,
    outcome: OutcomeT | None = None,
    store_id: UUID | None = None,
    mode: RunModeT | None = None,
    run_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> DecisionPage:
    return await _console.list_decisions(
        session,
        cursor=cursor,
        page_size=page_size,
        agent_key=agent_key,
        decision_type=decision_type,
        outcome=outcome,
        store_id=store_id,
        mode=mode,
        run_id=run_id,
        q=q,
    )


@router.get("/agent-decisions/stats", response_model=list[DecisionStatDTO])
async def decision_stats(
    _admin: RequireSuperAdmin, session: DbSession, agent_key: str | None = None
) -> list[DecisionStatDTO]:
    """Acceptance per agent and decision type (live decisions only) — feeds the Objective III evaluation."""
    return await _console.decision_stats(session, agent_key)


@router.get("/pipeline/runs", response_model=PipelinePage)
async def list_pipeline_runs(
    _admin: RequireSuperAdmin,
    session: DbSession,
    cursor: Cursor = None,
    page_size: PageSize = 20,
    trigger_type: TriggerTypeT | None = None,
    status_: Annotated[RunStatusT | None, Query(alias="status")] = None,
) -> PipelinePage:
    """Root runs (nightly and manual triggers) with their stages in order."""
    return await _console.list_pipeline_runs(
        session, cursor=cursor, page_size=page_size, trigger_type=trigger_type, status=status_
    )


@router.get("/pipeline/runs/{run_id}/graph", response_model=RunGraphDTO)
async def pipeline_graph(
    run_id: UUID | Literal["latest"], _admin: RequireSuperAdmin, session: DbSession
) -> RunGraphDTO:
    """Visual flow of one run: agents, key tools and human approval gates (fixed layout)."""
    return await _console.run_graph(session, run_id)
