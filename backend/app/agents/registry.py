"""Agent registry (docs/09 §1, D-50): every agent — the six deterministic pipeline stages and the five Objective III
LLM agents (one per pattern of docs/08 §3) — is described here once. The console, the orchestrator's config snapshot
and the `agent_definition` table all read this list; adding an agent means registering it here (and writing its card
under docs/agents/), never changing the screens.

Pure data: no database or framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Group = Literal["PIPELINE", "OBJECTIVE_III"]
Kind = Literal["DETERMINISTIC", "LLM"]
Pattern = Literal["PIPELINE_STAGE", "RETRIEVAL", "VALIDATION", "ACTION", "COORDINATOR", "REVIEWER"]


@dataclass(frozen=True)
class StoppingConditions:
    max_tool_calls: int | None = None
    max_tokens: int | None = None
    timeout_s: int | None = None
    other: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    group: Group
    kind: Kind
    pattern: Pattern
    critical: bool
    purpose: str
    #: required upstream agents (their outputs are inputs); a disabled required upstream skips this agent
    depends_on: tuple[str, ...] = ()
    #: upstream agents whose outputs are used when present (the agent runs without them and says so)
    optional_inputs: tuple[str, ...] = ()
    class_name: str | None = None  # BaseAgent.name of the implementation (agent_run.agent_name)
    delegation: str = ""
    description: str = ""
    discernment: str = ""
    diligence: str = ""
    input_contract: str = ""
    output_contract: str = ""
    read_tools: tuple[str, ...] = ()
    draft_tools: tuple[str, ...] = ()
    stopping: StoppingConditions = field(default_factory=StoppingConditions)
    prompt_version: str | None = None
    business_rules: tuple[str, ...] = ()
    disabled_effect: str = ""
    human_in_the_loop: str = ""
    #: "Run now" support: PIPELINE stages and batch LLM agents yes; Ask RetailPilot is question-driven
    triggerable: bool = True
    decision_types: tuple[str, ...] = ()

    @property
    def card_path(self) -> str:
        return f"docs/agents/{self.key}.md"


_PIPELINE_STOP = StoppingConditions(other=("RunParams.max_steps per stage", "2 attempts, then FAILED"))

AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        key="sales_analytics",
        name="Sales Analytics",
        group="PIPELINE",
        kind="DETERMINISTIC",
        pattern="PIPELINE_STAGE",
        critical=False,
        class_name="SalesAnalyticsAgent",
        purpose="Store KPIs (28-day revenue) and lost revenue / lost profit per store-SKU (separate KPIs, rule 9).",
        delegation="Not delegated to an LLM: every figure is a calculation (tools/lost_sales.py).",
        description="SD-03; spec §8. Inputs: sales lines and snapshots of the lookback window.",
        discernment="Unit tests of the lost-sales tool; KPI totals reconcile with the sales ledger.",
        diligence="Logged through AgentRunLogger; no human approval (informational outputs).",
        input_contract="RunContext (run_id, run_date, store_ids, RunParams)",
        output_contract="kpi_snapshot rows, lost_sales_estimate rows",
        read_tools=("compute_kpis", "estimate_lost_sales"),
        stopping=_PIPELINE_STOP,
        business_rules=("kpi_lookback_days",),
        disabled_effect='KPIs and lost revenue/profit are not refreshed; screens show "as of <last run>".',
        human_in_the_loop="None — informational KPIs.",
    ),
    AgentSpec(
        key="demand_forecasting",
        name="Demand Forecasting",
        group="PIPELINE",
        kind="DETERMINISTIC",
        pattern="PIPELINE_STAGE",
        critical=True,
        class_name="DemandForecastingAgent",
        purpose="Daily demand per store-SKU with method and HIGH/LOW confidence (D-45).",
        delegation="Not delegated: forecasting is a numeric model (tools/forecast.py); an LLM adds no accuracy.",
        description="SD-04; spec §8. Baseline / Croston / TSB / IMAPA; model selection off by default (D-45).",
        discernment="28-day replay evaluation (docs/EVALUATION_REPORT.md), WMAPE and bias per method.",
        diligence="LOW confidence never auto-transfers: it routes to NEEDS_REVIEW (D-04).",
        input_contract="RunContext; sales history (forecast_lookback_days)",
        output_contract="forecast rows (daily_demand, method, confidence)",
        read_tools=("forecast_demand",),
        stopping=_PIPELINE_STOP,
        business_rules=("min_history_days", "stale_days"),
        disabled_effect="Critical: nightly replenishment is PAUSED — no new recommendations or POs; users keep the "
        "last results.",
        human_in_the_loop="None directly; LOW confidence items reach humans as NEEDS_REVIEW.",
    ),
    AgentSpec(
        key="related_product",
        name="Related Products",
        group="PIPELINE",
        kind="DETERMINISTIC",
        pattern="PIPELINE_STAGE",
        critical=False,
        class_name="RelatedProductAgent",
        purpose="Basket association rules (support, confidence, lift) and assortment gaps.",
        delegation="Not delegated: market-basket statistics are deterministic (tools/basket.py).",
        description="SD-05; basket.* business rules.",
        discernment="Planted bread→butter pair recovered in tests (scenario 4).",
        diligence="Assortment gaps are recommendations a supervisor accepts or rejects.",
        input_contract="RunContext; cleaned bills (returns/voids/promo days excluded)",
        output_contract="association_rule rows; ASSORTMENT_GAP recommendations",
        read_tools=("mine_association_rules",),
        stopping=_PIPELINE_STOP,
        business_rules=("basket",),
        disabled_effect="No co-replenishment and no assortment gaps; Stock Balancing runs without them and says so "
        "in its run log.",
        human_in_the_loop="Assortment gaps: supervisor accept / reject in the inbox.",
        decision_types=("ASSORTMENT_GAP_FOUND",),
    ),
    AgentSpec(
        key="stock_balancing",
        name="Stock Balancing",
        group="PIPELINE",
        kind="DETERMINISTIC",
        pattern="PIPELINE_STAGE",
        critical=True,
        class_name="StockBalancingAgent",
        depends_on=("demand_forecasting",),
        optional_inputs=("sales_analytics", "related_product"),
        purpose="Requirement, surplus, transfer-vs-PO (incremental costs), donor protection, co-replenishment.",
        delegation="Not delegated: rules 1–5 are exact formulas (tools/requirement.py, transfer_engine.py).",
        description="SD-06, SD-07; worked example: Store C need 40, Store A surplus 24 → transfer 24 + PO 16.",
        discernment="Property tests: a donor never goes below its own requirement; costs are incremental only.",
        diligence="Transfers need destination acceptance and donor release; PO needs go to L1/L2.",
        input_contract="RunContext; forecasts of this run (+ lost sales, association rules when present)",
        output_contract="TRANSFER / REORDER / CO_REPLENISH recommendations, replenishment needs, PROPOSED transfers",
        read_tools=("requirement", "transfer_decision_engine"),
        stopping=_PIPELINE_STOP,
        business_rules=("order_fixed_cost", "holding_cost_rate_per_day", "expiry_risk_pct", "co_replenish"),
        disabled_effect="Critical: nightly replenishment is PAUSED (double confirmation to turn off).",
        human_in_the_loop="Transfer: destination accepts → donor releases. PO need: L1 per store, L2 above threshold.",
        decision_types=(
            "TRANSFER_CHOSEN_OVER_PO",
            "PO_NEED_CREATED",
            "CO_REPLENISH_LINKED",
            "NEEDS_REVIEW_RAISED",
        ),
    ),
    AgentSpec(
        key="freshness",
        name="Freshness",
        group="PIPELINE",
        kind="DETERMINISTIC",
        pattern="PIPELINE_STAGE",
        critical=False,
        class_name="FreshnessAgent",
        depends_on=("demand_forecasting",),
        purpose="Expiry risk per batch: expiry transfers to stores that sell it in time, or expiry alerts.",
        delegation="Not delegated: days-to-sell vs days-to-expiry is arithmetic (tools/freshness.py).",
        description="SD-08; expiry_window_days.",
        discernment="Scenario 5 (expiry transfer) asserted end to end.",
        diligence="Expiry transfers follow the normal transfer approvals.",
        input_contract="RunContext; batches, forecasts of this run",
        output_contract="TRANSFER (expiry) and EXPIRY_ALERT recommendations",
        read_tools=("expiry_risk",),
        stopping=_PIPELINE_STOP,
        business_rules=("expiry_window_days", "perishable_max_shelf_life_days"),
        disabled_effect='No expiry transfers or alerts; the inventory screen shows "Expiry checks off".',
        human_in_the_loop="Expiry transfers: destination accepts, donor releases.",
        decision_types=("EXPIRY_TRANSFER", "EXPIRY_ALERT_RAISED"),
    ),
    AgentSpec(
        key="purchase_order",
        name="Purchase Orders",
        group="PIPELINE",
        kind="DETERMINISTIC",
        pattern="PIPELINE_STAGE",
        critical=True,
        class_name="PurchaseOrderAgent",
        depends_on=("stock_balancing",),
        purpose="Consolidated supplier POs from replenishment needs (MOQ, case packs, budget, L1 deadline).",
        delegation="Not delegated: PO building is deterministic (tools/po_builder.py); the LLM only explains.",
        description="SD-09; explanations via ExplanationService (numbers checked against evidence).",
        discernment="ExplanationService rejects any LLM text containing a number not in the evidence.",
        diligence="Every PO is PENDING_L1; never sent to a real supplier (SimulatedSupplierGateway).",
        input_contract="RunContext; replenishment needs and recommendations of this run",
        output_contract="purchase_order + po_line rows (PENDING_L1)",
        read_tools=("po_builder", "explain"),
        stopping=_PIPELINE_STOP,
        business_rules=("po_l2_threshold", "l1_deadline_hours"),
        disabled_effect="Critical: nightly replenishment is PAUSED.",
        human_in_the_loop="L1 line approval per store; L2 above the threshold.",
        decision_types=("PO_DRAFTED",),
    ),
    # --- Objective III (docs/08 §3): LLM agents that choose which approved tools to call; tools calculate ------
    AgentSpec(
        key="ask_retailpilot",
        name="Ask RetailPilot",
        group="OBJECTIVE_III",
        kind="LLM",
        pattern="RETRIEVAL",
        critical=False,
        purpose='Answers questions such as "Why are we ordering butter?" from recommendations, evidence, business '
        "rules and SOP/policy text — always with citations, or says it was not found.",
        delegation="Open-ended natural-language questions: the agent chooses what to retrieve. A fixed screen "
        "cannot answer arbitrary questions.",
        description="Prompt ask_retailpilot.v1; output AskAnswer (answer, citations[], found, refused).",
        discernment="Code checks: every citation was returned by a tool in this run; every number in the answer "
        "appears in a tool result. LLM-as-judge for groundedness on the eval set.",
        diligence="Read-only tools, scoped to the asking user's store (rule 10). Requests to approve / submit / "
        "change stock are refused.",
        input_contract="AskRequest {question (3–500 chars)} + the calling user's role and store",
        output_contract="AskAnswer {answer, found, refused, citations[{source_type, source_id, label}]}",
        read_tools=(
            "search_records",
            "search_policies",
            "get_recommendation",
            "get_evidence",
            "get_inventory_position",
            "get_business_rules",
            "list_transfers",
        ),
        stopping=StoppingConditions(
            max_tool_calls=6,
            max_tokens=12_000,
            timeout_s=45,
            other=("submit_answer called", "cannot answer → found=false with reason"),
        ),
        prompt_version="ask_retailpilot.v1",
        disabled_effect='The Ask RetailPilot page shows "Agent disabled"; nothing else changes.',
        human_in_the_loop="None — answers only; it cannot act.",
        triggerable=False,
        decision_types=("ANSWER_GIVEN", "NOT_FOUND", "REQUEST_REFUSED"),
    ),
    AgentSpec(
        key="data_quality",
        name="Data Quality",
        group="OBJECTIVE_III",
        kind="LLM",
        pattern="VALIDATION",
        critical=False,
        purpose="Triages ingestion results (stale SKUs, snapshot mismatches, anomalies) into a likely cause and "
        "a next step; proposes data-review items with evidence.",
        delegation="Mixed signals → a cause and next step is interpretation; SD-02 rules only flag.",
        description="Prompt data_quality.v1; output DQReport (summary, issues[DQIssue{category, likely_cause, "
        "severity, evidence_ids, next_step}]).",
        discernment="Each issue must cite evidence returned by get_ingestion_report / get_inventory_position; the "
        "category must be one of the allowed list.",
        diligence="It can only create DATA_REVIEW_ITEM drafts; it never edits stock or sales (rule 8).",
        input_contract="RunContext (run_date) — the latest ingestion validation report",
        output_contract="DQReport; DATA_REVIEW_ITEM drafts (created by code for MEDIUM/HIGH issues)",
        read_tools=("get_ingestion_report", "get_inventory_position", "get_run_log"),
        draft_tools=("create_data_review_item",),
        stopping=StoppingConditions(
            max_tool_calls=10, max_tokens=16_000, timeout_s=60, other=("submit_report called",)
        ),
        prompt_version="data_quality.v1",
        business_rules=("stale_days",),
        disabled_effect="Ingestion flags are shown as rule-based flags only (SD-02); no triage.",
        human_in_the_loop="Super Admin reviews data-review items.",
        decision_types=("DATA_ISSUE_CLASSIFIED", "NEEDS_REVIEW_RAISED"),
    ),
    AgentSpec(
        key="replenishment_action",
        name="Replenishment Action",
        group="OBJECTIVE_III",
        kind="LLM",
        pattern="ACTION",
        critical=False,
        depends_on=("stock_balancing",),
        purpose="For exception cases (NEEDS_REVIEW lines) assembles a transfer-or-PO proposal from tool results "
        "and returns a structured DRAFT — it can never approve or submit.",
        delegation="Exceptions where the rules leave a gap (low-confidence forecast, no eligible supplier) need a "
        "composed proposal across several tools.",
        description="Prompt replenishment_action.v1; output ActionDraft (draft_type, qty, rationale, tool "
        "evidence).",
        discernment="qty must equal a quantity returned by a tool (need, surplus or MOQ-rounded qty); donor "
        "protection re-checked in code.",
        diligence="create_draft_recommendation is the only write tool; drafts reach a human through the existing "
        "recommendation / transfer / PO approvals.",
        input_contract="rec_id of a NEEDS_REVIEW recommendation; batch mode (coordinator INVOKE or Run now): up to 10 per run",
        output_contract="ActionDraft; agent_draft row (TRANSFER_DRAFT | PO_DRAFT)",
        read_tools=(
            "get_recommendation",
            "get_evidence",
            "get_inventory_position",
            "get_transfer_options",
            "get_business_rules",
        ),
        draft_tools=("create_draft_recommendation",),
        stopping=StoppingConditions(
            max_tool_calls=8,
            max_tokens=16_000,
            timeout_s=60,
            other=("submit_draft called", "no viable option"),
        ),
        prompt_version="replenishment_action.v1",
        disabled_effect="No agent drafts; NEEDS_REVIEW items are decided manually as today.",
        human_in_the_loop="Draft → supervisor decision on the recommendation (accept/edit/reject).",
        decision_types=("DRAFT_CREATED",),
    ),
    AgentSpec(
        key="run_coordinator",
        name="Run Coordinator",
        group="OBJECTIVE_III",
        kind="LLM",
        pattern="COORDINATOR",
        critical=False,
        purpose="After the deterministic run, chooses how to handle failures and exceptions within an allow-list: "
        "retry an agent, mark PARTIAL, escalate to the Super Admin, or invoke agents 2/3/5.",
        delegation="Choosing among recovery paths from logs and context; the deterministic orchestrator (SD-01) "
        "stays the primary path.",
        description="Prompt run_coordinator.v1; output CoordinatorPlan (actions[{action, agent_key, reason}]).",
        discernment="Code rejects any action outside the allow-list or any retry of a critical agent beyond 1.",
        diligence="It cannot change data itself; it only invokes registered agents or notifies the Super Admin.",
        input_contract="The finished nightly run (stage statuses, errors, exception counts)",
        output_contract="CoordinatorPlan; executed actions recorded as decisions",
        read_tools=("get_run_log", "get_exception_summary"),
        stopping=StoppingConditions(
            max_tool_calls=4,
            max_tokens=8_000,
            timeout_s=30,
            other=("submit_plan called", "clean run → no LLM call", "≤ 3 actions"),
        ),
        prompt_version="run_coordinator.v1",
        disabled_effect="The deterministic orchestrator handles failures (current SD-01 behaviour).",
        human_in_the_loop="Escalations notify the Super Admin.",
        decision_types=(
            "COORDINATOR_RETRY",
            "COORDINATOR_ESCALATE",
            "COORDINATOR_MARK_PARTIAL",
            "COORDINATOR_INVOKE",
            "COORDINATOR_NO_ACTION",
        ),
    ),
    AgentSpec(
        key="recommendation_reviewer",
        name="Recommendation Reviewer",
        group="OBJECTIVE_III",
        kind="LLM",
        pattern="REVIEWER",
        critical=False,
        depends_on=("stock_balancing",),
        purpose="Checks each recommendation before the inbox: explanation grounded in evidence, policy compliance "
        "(donor protection, scoping, quantities) — flags issues.",
        delegation="Judging the quality of text and reasoning; code checks numbers and policies, the LLM judges "
        "whether the wording is supported.",
        description="Prompt recommendation_reviewer.v1; output ReviewVerdicts (per rec: verdict, issues[]).",
        discernment="Deterministic checks always run; the LLM judge only adds groundedness issues.",
        diligence="It never changes a recommendation; it labels it (Reviewed / Flagged / Not reviewed).",
        input_contract="Recommendations of the run (evidence + explanation)",
        output_contract="recommendation_review rows; REVIEWER_FLAGGED decisions",
        stopping=StoppingConditions(
            max_tool_calls=0,
            other=(
                "no tool loop: reads the run's recommendations directly",
                "LLM judge on at most 40 items, batches of 20",
                "judge error → code checks only",
            ),
        ),
        prompt_version="recommendation_reviewer.v1",
        disabled_effect='Recommendations still reach the inbox, labelled "Not reviewed".',
        human_in_the_loop="Flags are shown to the supervisor on the recommendation.",
        decision_types=("REVIEWER_FLAGGED",),
    ),
)

BY_KEY: dict[str, AgentSpec] = {a.key: a for a in AGENTS}
BY_CLASS_NAME: dict[str, AgentSpec] = {a.class_name: a for a in AGENTS if a.class_name}
PIPELINE_KEYS: tuple[str, ...] = tuple(a.key for a in AGENTS if a.group == "PIPELINE")
LLM_KEYS: tuple[str, ...] = tuple(a.key for a in AGENTS if a.kind == "LLM")


def get_spec(key: str) -> AgentSpec | None:
    return BY_KEY.get(key)


def upstream_closure(key: str) -> list[str]:
    """Required upstream agents of `key`, transitively, in pipeline order."""
    seen: set[str] = set()

    def visit(k: str) -> None:
        for dep in BY_KEY[k].depends_on:
            if dep not in seen:
                seen.add(dep)
                visit(dep)

    visit(key)
    return [a.key for a in AGENTS if a.key in seen]


def downstream_dependants(key: str) -> list[str]:
    """Agents that require `key` (transitively), in registry order."""
    out: set[str] = set()
    changed = True
    while changed:
        changed = False
        for a in AGENTS:
            if a.key not in out and any(d == key or d in out for d in a.depends_on):
                out.add(a.key)
                changed = True
    return [a.key for a in AGENTS if a.key in out]
