"""DTOs of the agent console and the Objective III agents (docs/09 §5, docs/08, D-50). Super Admin only, except
`AskRequest` / `AskAnswerDTO` (any signed-in user, scoped to their store)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, PlainSerializer, WithJsonSchema

from app.domain.schemas.common import DTO, CursorPage, ProductRef, StoreRef

AgentGroupT = Literal["PIPELINE", "OBJECTIVE_III"]
AgentKindT = Literal["DETERMINISTIC", "LLM"]
AgentPatternT = Literal["PIPELINE_STAGE", "RETRIEVAL", "VALIDATION", "ACTION", "COORDINATOR", "REVIEWER"]
RunStatusT = Literal[
    "RUNNING", "SUCCESS", "FAILED", "PARTIAL", "SKIPPED_DISABLED", "SKIPPED_DEPENDENCY", "PAUSED", "CANCELLED"
]
TriggerTypeT = Literal["NIGHTLY", "MANUAL_DRY_RUN", "MANUAL_LIVE", "ON_DEMAND"]
RunModeT = Literal["LIVE", "DRY_RUN"]
OutcomeT = Literal["PENDING", "ACCEPTED", "EDITED", "REJECTED", "SUPERSEDED", "NOT_APPLICABLE"]

#: estimated provider cost in USD (fractions of a cent) — a 6-decimal string, never a business figure
UsdCost = Annotated[
    Decimal,
    PlainSerializer(
        lambda v: format(Decimal(v).quantize(Decimal("0.000001")), "f"), return_type=str, when_used="json"
    ),
    WithJsonSchema({"type": "string", "description": "Estimated provider cost in USD, 6 decimals"}),
]


class LastRunRef(DTO):
    run_id: UUID
    status: RunStatusT
    started_at: datetime
    finished_at: datetime | None


class AgentSummaryDTO(DTO):
    agent_key: str
    name: str
    group: AgentGroupT
    kind: AgentKindT
    pattern: AgentPatternT
    critical: bool
    purpose: str
    enabled: bool = Field(description="The agent's own switch")
    effective_enabled: bool = Field(
        description="Own switch AND (not an LLM agent OR the global LLM switch is on)"
    )
    depends_on: list[str]
    optional_inputs: list[str]
    triggerable: bool
    last_run: LastRunRef | None
    runs_7d: int
    success_rate_7d: float | None = Field(description="SUCCESS / finished runs of the last 7 days (0–1)")
    p95_latency_ms: int | None
    tokens_7d: int
    est_cost_7d_usd: UsdCost
    recommendations_7d: int = Field(
        description="Live decisions of the last 7 days (recommendations, POs, flags, answers…)"
    )
    acceptance_rate: float | None = Field(
        description="Accepted or edited / decided (all time, live decisions)"
    )


class AgentListDTO(DTO):
    items: list[AgentSummaryDTO]
    llm_enabled: bool = Field(description='Global "All LLM agents" switch')
    config_version: int
    paused_banner: str | None = Field(
        description='"Replenishment paused by <user>: <reason>" when a critical pipeline agent is off'
    )


class StoppingDTO(DTO):
    max_tool_calls: int | None
    max_tokens: int | None
    timeout_s: int | None
    other: list[str]


class RuleValueDTO(DTO):
    key: str
    value: Any


class ToggleEventDTO(DTO):
    config_version: int
    agent_key: str | None = Field(description="null = the global LLM switch")
    enabled: bool
    previous_enabled: bool | None
    reason: str
    updated_by: str | None = Field(description="Name of the user; null for the seeded initial version")
    created_at: datetime
    is_demo: bool = False


class EvalResultDTO(DTO):
    agent_key: str
    source: Literal["RECORDED", "LIVE"]
    variant: Literal["AGENT", "BASELINE"]
    cases: int
    correctness: float
    groundedness: float
    tool_use: float
    failure_handling: float
    latency_p50_ms: int
    latency_p95_ms: int
    tokens: int
    est_cost_usd: UsdCost
    human_agreement: float | None
    created_at: datetime


class AgentDetailDTO(DTO):
    agent: AgentSummaryDTO
    delegation: str
    description: str
    discernment: str
    diligence: str
    input_contract: str
    output_contract: str
    read_tools: list[str]
    draft_tools: list[str]
    stopping: StoppingDTO
    prompt_version: str | None
    prompt_text: str | None = Field(description="System instructions of the LLM agent (versioned file)")
    business_rules: list[RuleValueDTO] = Field(description="Parameters (edit in Settings → business rules)")
    disabled_effect: str
    human_in_the_loop: str
    decision_types: list[str]
    card_markdown: str | None = Field(description="docs/agents/<key>.md")
    toggle_history: list[ToggleEventDTO]
    evals: list[EvalResultDTO]


class ToggleAgentRequest(DTO):
    enabled: bool
    reason: str = Field(min_length=5, max_length=500)
    confirm_critical: bool = Field(
        False, description="Second confirmation, required to turn OFF a critical agent (pauses replenishment)"
    )


class ToggleLLMRequest(DTO):
    enabled: bool
    reason: str = Field(min_length=5, max_length=500)


class TriggerAgentRequest(DTO):
    mode: RunModeT = "DRY_RUN"
    reason: str | None = Field(None, max_length=500, description="Required for LIVE")
    confirm: bool = Field(False, description="LIVE: the user confirmed the consequences")


class UpstreamStatusDTO(DTO):
    agent_key: str
    fresh: bool
    action: Literal["REUSE", "RERUN", "SKIP_DISABLED"]


class TriggerPreviewDTO(DTO):
    agent_key: str
    mode: RunModeT
    allowed: bool
    blocked_reason: str | None
    upstream: list[UpstreamStatusDTO]
    downstream: list[str] = Field(description="Dependants re-run in LIVE mode (skipped in a dry run)")
    recommendations_to_supersede: int = Field(
        description="LIVE: PENDING recommendations of the re-run agents"
    )
    live_triggers_last_hour: int
    live_trigger_limit: int
    consequences: list[str]


class TriggerResultDTO(DTO):
    run_id: UUID
    mode: RunModeT
    status: RunStatusT
    message: str


class AgentRunItemDTO(DTO):
    run_id: UUID
    parent_run_id: UUID | None
    agent_key: str | None
    agent_name: str
    trigger_type: TriggerTypeT
    mode: RunModeT
    status: RunStatusT
    run_date: date | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    tool_calls: int
    llm_calls: int
    tokens: int
    est_cost_usd: UsdCost
    retries: int
    stop_reason: str | None
    error: str | None
    triggered_by: str | None
    reason: str | None
    is_demo: bool = Field(False, description="Seeded demo activity (scripts.seed_agents --demo)")


class TraceStepDTO(DTO):
    kind: Literal["TOOL", "LLM", "CHILD_RUN", "ERROR", "STOP"]
    at: datetime
    name: str
    status: str
    duration_ms: int | None = None
    args_summary: str | None = None
    result_summary: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    est_cost_usd: UsdCost | None = None
    run_id: UUID | None = None


class PreviewOutputDTO(DTO):
    agent_key: str
    output_type: str
    payload: dict[str, Any]


class AgentRunTraceDTO(DTO):
    run: AgentRunItemDTO
    input_ref: dict[str, Any]
    output_summary: Any
    config_version: int | None
    config_snapshot: dict[str, Any] | None
    children: list[AgentRunItemDTO]
    steps: list[TraceStepDTO]
    previews: list[PreviewOutputDTO]
    decisions: int


class AgentDecisionDTO(DTO):
    decision_id: UUID
    run_id: UUID
    agent_key: str
    agent_name: str
    decision_type: str
    mode: RunModeT
    store: StoreRef | None
    product: ProductRef | None
    summary: str
    rec_id: UUID | None
    transfer_id: UUID | None
    po_id: UUID | None
    draft_id: UUID | None
    evidence_ref: dict[str, Any]
    outcome: OutcomeT
    outcome_reason: str | None
    outcome_at: datetime | None
    created_at: datetime
    is_demo: bool = False


class DecisionStatDTO(DTO):
    agent_key: str
    decision_type: str
    total: int
    accepted: int
    edited: int
    rejected: int
    pending: int
    superseded: int
    acceptance_rate: float | None = Field(description="(accepted + edited) / (accepted + edited + rejected)")


class PipelineStageDTO(DTO):
    agent_key: str
    name: str
    status: RunStatusT | Literal["NOT_RUN"]
    run_id: UUID | None
    duration_ms: int | None
    retries: int
    outputs: int | None
    error: str | None


class PipelineRunDTO(DTO):
    run_id: UUID
    run_date: date | None
    agent_key: str | None = Field(description="Target agent of a manual trigger; null for nightly")
    trigger_type: TriggerTypeT
    mode: RunModeT
    status: RunStatusT
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    config_version: int | None
    triggered_by: str | None
    reason: str | None
    stop_reason: str | None
    stages: list[PipelineStageDTO]
    escalations: int
    has_partial: bool
    is_demo: bool = False


class GraphNodeDTO(DTO):
    id: str
    label: str
    node_type: Literal["AGENT", "TOOL", "GATE", "DATA"]
    agent_key: str | None
    status: RunStatusT | Literal["NOT_RUN", "WAITING", "DONE"] | None
    run_id: UUID | None
    x: int
    y: int
    detail: str | None


class GraphEdgeDTO(DTO):
    source: str
    target: str
    label: str | None
    kind: Literal["DATA", "REVIEW", "EXCEPTION", "APPROVAL"]


class RunGraphDTO(DTO):
    run_id: UUID
    status: RunStatusT
    in_progress: bool
    nodes: list[GraphNodeDTO]
    edges: list[GraphEdgeDTO]


class DailyRunCountDTO(DTO):
    day: date
    success: int
    failed: int
    other: int


class AgentStatsDTO(DTO):
    agent_key: str
    runs_by_day: list[DailyRunCountDTO]
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    decisions_by_type: list[DecisionStatDTO]


# --- Ask RetailPilot ------------------------------------------------------------------------------------------------


class AskRequest(DTO):
    question: str = Field(min_length=3, max_length=500)


class CitationDTO(DTO):
    source_type: Literal["RECOMMENDATION", "EVIDENCE", "BUSINESS_RULE", "POLICY", "TRANSFER", "INVENTORY"]
    source_id: str
    label: str


class AskAnswerDTO(DTO):
    answer: str
    found: bool
    refused: bool
    citations: list[CitationDTO]
    run_id: UUID | None
    latency_ms: int
    mode: Literal["LLM", "RETRIEVAL_ONLY"] = Field(
        description="RETRIEVAL_ONLY: no LLM (no key, or the global LLM switch is off) — sources listed, no prose"
    )


class AgentStatusDTO(DTO):
    """What every signed-in user may know about the agents (banners), D-54."""

    expiry_checks_on: bool = Field(
        description="Freshness agent on — else the inventory shows 'Expiry checks off'"
    )
    reviewer_on: bool
    ask_enabled: bool
    replenishment_paused: str | None = Field(description="'Replenishment paused by <user>: <reason>' or null")


class AskStatusDTO(DTO):
    enabled: bool
    examples: list[str]


AgentRunPage = CursorPage[AgentRunItemDTO]
DecisionPage = CursorPage[AgentDecisionDTO]
PipelinePage = CursorPage[PipelineRunDTO]
