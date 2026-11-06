/**
 * Mock agent console (docs/09, D-50) for UI-only work and tests (VITE_USE_MOCKS). Shapes are the generated DTO
 * types; values mirror backend/app/agents/registry.py and a plausible run history built from the fixture
 * recommendations. The real data comes from the API (Phase 5 registry, config, runs and decisions).
 */
import { ApiError, type ApiClient } from "../api/client";
import type {
  AgentDecisionDTO,
  AgentDetailDTO,
  AgentRunItemDTO,
  AgentRunTraceDTO,
  AgentSummaryDTO,
  CursorPage,
  DecisionStatDTO,
  GraphEdgeDTO,
  GraphNodeDTO,
  PipelineRunDTO,
  PipelineStageDTO,
  RunGraphDTO,
  RunStatus,
  ToggleEventDTO,
  TraceStepDTO,
} from "../api/types";
import type { MockFixtures, MockUser } from "./fixtures";

type AgentMethods = Pick<
  ApiClient,
  | "listAgents"
  | "getAgent"
  | "toggleAgent"
  | "toggleLlmAgents"
  | "getAgentStats"
  | "getTriggerPreview"
  | "triggerAgent"
  | "listAgentRuns"
  | "getAgentRun"
  | "cancelAgentRun"
  | "listDecisions"
  | "getDecisionStats"
  | "listPipelineRuns"
  | "getRunGraph"
  | "getAssistantStatus"
  | "getAgentStatus"
  | "ask"
>;

interface Spec {
  key: string;
  name: string;
  group: AgentSummaryDTO["group"];
  kind: AgentSummaryDTO["kind"];
  pattern: AgentSummaryDTO["pattern"];
  critical: boolean;
  purpose: string;
  depends_on: string[];
  optional_inputs: string[];
  triggerable: boolean;
  read_tools: string[];
  draft_tools: string[];
  prompt_version: string | null;
  disabled_effect: string;
  decision_types: string[];
}

const S = (s: Partial<Spec> & Pick<Spec, "key" | "name" | "kind" | "pattern" | "purpose">): Spec => ({
  group: s.kind === "LLM" ? "OBJECTIVE_III" : "PIPELINE",
  critical: false,
  depends_on: [],
  optional_inputs: [],
  triggerable: true,
  read_tools: [],
  draft_tools: [],
  prompt_version: null,
  disabled_effect: "",
  decision_types: [],
  ...s,
});

export const MOCK_SPECS: Spec[] = [
  S({
    key: "sales_analytics",
    name: "Sales Analytics",
    kind: "DETERMINISTIC",
    pattern: "PIPELINE_STAGE",
    purpose: "Store and SKU KPIs, ABC-XYZ classes, lost revenue and lost profit (separate KPIs, rule 9).",
    read_tools: ["compute_kpis", "estimate_lost_sales"],
    disabled_effect: 'KPIs and lost revenue/profit are not refreshed; screens show "as of <last run>".',
  }),
  S({
    key: "demand_forecasting",
    name: "Demand Forecasting",
    kind: "DETERMINISTIC",
    pattern: "PIPELINE_STAGE",
    critical: true,
    purpose: "Daily demand per store-SKU with method and HIGH/LOW confidence (D-45).",
    read_tools: ["forecast_demand"],
    disabled_effect: "Critical: nightly replenishment is PAUSED — no new recommendations or POs.",
  }),
  S({
    key: "related_product",
    name: "Related Products",
    kind: "DETERMINISTIC",
    pattern: "PIPELINE_STAGE",
    purpose: "Basket association rules (support, confidence, lift) and assortment gaps.",
    read_tools: ["mine_association_rules"],
    disabled_effect: "No co-replenishment and no assortment gaps; Stock Balancing runs without them.",
    decision_types: ["ASSORTMENT_GAP_FOUND"],
  }),
  S({
    key: "stock_balancing",
    name: "Stock Balancing",
    kind: "DETERMINISTIC",
    pattern: "PIPELINE_STAGE",
    critical: true,
    depends_on: ["demand_forecasting"],
    optional_inputs: ["sales_analytics", "related_product"],
    purpose: "Requirement, surplus, transfer-vs-PO (incremental costs), donor protection, co-replenishment.",
    read_tools: ["requirement", "transfer_decision_engine"],
    disabled_effect: "Critical: nightly replenishment is PAUSED (double confirmation to turn off).",
    decision_types: ["TRANSFER_CHOSEN_OVER_PO", "PO_NEED_CREATED", "CO_REPLENISH_LINKED", "NEEDS_REVIEW_RAISED"],
  }),
  S({
    key: "freshness",
    name: "Freshness",
    kind: "DETERMINISTIC",
    pattern: "PIPELINE_STAGE",
    depends_on: ["demand_forecasting"],
    purpose: "Expiry risk per batch: expiry transfers to stores that sell it in time, or expiry alerts.",
    read_tools: ["expiry_risk"],
    disabled_effect: 'No expiry transfers or alerts; the inventory screen shows "Expiry checks off".',
    decision_types: ["EXPIRY_TRANSFER", "EXPIRY_ALERT_RAISED"],
  }),
  S({
    key: "purchase_order",
    name: "Purchase Orders",
    kind: "DETERMINISTIC",
    pattern: "PIPELINE_STAGE",
    critical: true,
    depends_on: ["stock_balancing"],
    purpose: "Consolidated supplier POs from replenishment needs (MOQ, case packs, budget, L1 deadline).",
    read_tools: ["po_builder", "explain"],
    disabled_effect: "Critical: nightly replenishment is PAUSED.",
    decision_types: ["PO_DRAFTED"],
  }),
  S({
    key: "ask_retailpilot",
    name: "Ask RetailPilot",
    kind: "LLM",
    pattern: "RETRIEVAL",
    triggerable: false,
    purpose: "Answers questions from recommendations, evidence, business rules and SOP/policy text, with citations.",
    read_tools: ["search_records", "search_policies", "get_recommendation", "get_evidence", "get_business_rules"],
    prompt_version: "ask_retailpilot.v1",
    disabled_effect: 'The Ask RetailPilot page shows "Agent disabled".',
    decision_types: ["ANSWER_GIVEN", "NOT_FOUND", "REQUEST_REFUSED"],
  }),
  S({
    key: "data_quality",
    name: "Data Quality",
    kind: "LLM",
    pattern: "VALIDATION",
    purpose: "Triages ingestion results into a likely cause and next step; proposes data-review items.",
    read_tools: ["get_ingestion_report", "get_inventory_position", "get_run_log"],
    draft_tools: ["create_data_review_item"],
    prompt_version: "data_quality.v1",
    disabled_effect: "Ingestion flags are shown as rule-based flags only (SD-02).",
    decision_types: ["DATA_ISSUE_CLASSIFIED", "NEEDS_REVIEW_RAISED"],
  }),
  S({
    key: "replenishment_action",
    name: "Replenishment Action",
    kind: "LLM",
    pattern: "ACTION",
    depends_on: ["stock_balancing"],
    purpose: "Assembles a transfer-or-PO DRAFT for NEEDS_REVIEW exceptions — it can never approve or submit.",
    read_tools: ["get_recommendation", "get_evidence", "get_inventory_position", "get_transfer_options"],
    draft_tools: ["create_draft_recommendation"],
    prompt_version: "replenishment_action.v1",
    disabled_effect: "No agent drafts; NEEDS_REVIEW items are decided manually as today.",
    decision_types: ["DRAFT_CREATED"],
  }),
  S({
    key: "run_coordinator",
    name: "Run Coordinator",
    kind: "LLM",
    pattern: "COORDINATOR",
    purpose: "Chooses how to handle failures and exceptions within an allow-list: retry, mark PARTIAL, escalate.",
    read_tools: ["get_run_log", "get_exception_summary"],
    prompt_version: "run_coordinator.v1",
    disabled_effect: "The deterministic orchestrator handles failures (current SD-01 behaviour).",
    decision_types: ["COORDINATOR_RETRY", "COORDINATOR_ESCALATE", "COORDINATOR_INVOKE", "COORDINATOR_NO_ACTION"],
  }),
  S({
    key: "recommendation_reviewer",
    name: "Recommendation Reviewer",
    kind: "LLM",
    pattern: "REVIEWER",
    depends_on: ["stock_balancing"],
    purpose: "Checks each recommendation before the inbox: groundedness and policy compliance; flags issues.",
    read_tools: ["get_recommendation", "get_evidence"],
    prompt_version: "recommendation_reviewer.v1",
    disabled_effect: 'Recommendations still reach the inbox, labelled "Not reviewed".',
    decision_types: ["REVIEWER_FLAGGED"],
  }),
];

const PIPELINE_ORDER = [
  "data_quality",
  "sales_analytics",
  "demand_forecasting",
  "related_product",
  "stock_balancing",
  "freshness",
  "purchase_order",
  "recommendation_reviewer",
  "run_coordinator",
];

const COL = [20, 250, 480, 710, 940, 1170];
const ROW = [20, 120, 220, 320, 420];

/** Fixed layout of the visual flow — same positions as the backend graph (D-50). */
export const GRAPH_LAYOUT: Array<Pick<GraphNodeDTO, "id" | "label" | "node_type" | "agent_key" | "x" | "y">> = [
  { id: "ingestion", label: "POS ingestion", node_type: "DATA", agent_key: null, x: COL[0]!, y: ROW[2]! },
  { id: "data_quality", label: "Data Quality", node_type: "AGENT", agent_key: "data_quality", x: COL[1]!, y: ROW[0]! },
  {
    id: "sales_analytics",
    label: "Sales Analytics",
    node_type: "AGENT",
    agent_key: "sales_analytics",
    x: COL[1]!,
    y: ROW[1]!,
  },
  {
    id: "demand_forecasting",
    label: "Demand Forecasting",
    node_type: "AGENT",
    agent_key: "demand_forecasting",
    x: COL[1]!,
    y: ROW[2]!,
  },
  {
    id: "related_product",
    label: "Related Products",
    node_type: "AGENT",
    agent_key: "related_product",
    x: COL[1]!,
    y: ROW[3]!,
  },
  {
    id: "stock_balancing",
    label: "Stock Balancing",
    node_type: "AGENT",
    agent_key: "stock_balancing",
    x: COL[2]!,
    y: ROW[2]!,
  },
  { id: "tool_transfer_engine", label: "Transfer engine", node_type: "TOOL", agent_key: null, x: COL[2]!, y: ROW[1]! },
  { id: "freshness", label: "Freshness", node_type: "AGENT", agent_key: "freshness", x: COL[3]!, y: ROW[1]! },
  {
    id: "purchase_order",
    label: "Purchase Orders",
    node_type: "AGENT",
    agent_key: "purchase_order",
    x: COL[3]!,
    y: ROW[3]!,
  },
  {
    id: "recommendation_reviewer",
    label: "Recommendation Reviewer",
    node_type: "AGENT",
    agent_key: "recommendation_reviewer",
    x: COL[4]!,
    y: ROW[2]!,
  },
  { id: "gate_human", label: "Human approval", node_type: "GATE", agent_key: null, x: COL[5]!, y: ROW[2]! },
  {
    id: "run_coordinator",
    label: "Run Coordinator",
    node_type: "AGENT",
    agent_key: "run_coordinator",
    x: COL[2]!,
    y: ROW[4]!,
  },
  {
    id: "replenishment_action",
    label: "Replenishment Action",
    node_type: "AGENT",
    agent_key: "replenishment_action",
    x: COL[4]!,
    y: ROW[4]!,
  },
  {
    id: "ask_retailpilot",
    label: "Ask RetailPilot",
    node_type: "AGENT",
    agent_key: "ask_retailpilot",
    x: COL[0]!,
    y: ROW[4]!,
  },
];

export const GRAPH_EDGES: GraphEdgeDTO[] = [
  { source: "ingestion", target: "data_quality", label: "issues", kind: "EXCEPTION" },
  { source: "ingestion", target: "sales_analytics", label: null, kind: "DATA" },
  { source: "ingestion", target: "demand_forecasting", label: "sales history", kind: "DATA" },
  { source: "ingestion", target: "related_product", label: null, kind: "DATA" },
  { source: "sales_analytics", target: "stock_balancing", label: "lost sales", kind: "DATA" },
  { source: "demand_forecasting", target: "stock_balancing", label: "forecasts", kind: "DATA" },
  { source: "related_product", target: "stock_balancing", label: "basket rules", kind: "DATA" },
  { source: "demand_forecasting", target: "freshness", label: "forecasts", kind: "DATA" },
  { source: "stock_balancing", target: "tool_transfer_engine", label: null, kind: "DATA" },
  { source: "stock_balancing", target: "purchase_order", label: "PO needs", kind: "DATA" },
  { source: "stock_balancing", target: "recommendation_reviewer", label: "recommendations", kind: "REVIEW" },
  { source: "freshness", target: "recommendation_reviewer", label: null, kind: "REVIEW" },
  { source: "purchase_order", target: "recommendation_reviewer", label: null, kind: "REVIEW" },
  { source: "recommendation_reviewer", target: "gate_human", label: "inbox", kind: "APPROVAL" },
  { source: "purchase_order", target: "run_coordinator", label: "run outcome", kind: "EXCEPTION" },
  { source: "run_coordinator", target: "replenishment_action", label: "NEEDS_REVIEW", kind: "EXCEPTION" },
  { source: "replenishment_action", target: "gate_human", label: "drafts", kind: "APPROVAL" },
  { source: "data_quality", target: "gate_human", label: "review items", kind: "APPROVAL" },
];

const iso = (base: number, plusMs = 0) => new Date(base + plusMs).toISOString();

interface MockRun extends AgentRunItemDTO {
  input_ref: Record<string, unknown>;
  config_version: number | null;
}

function encodeCursor(index: number): string {
  return btoa(String(index)).replaceAll("=", "");
}
function decodeCursor(cursor: string | null | undefined): number {
  if (!cursor) return 0;
  const n = Number(atob(cursor));
  if (!Number.isInteger(n) || n < 0) throw new ApiError(422, "VALIDATION", "Invalid cursor");
  return n;
}
function cursorPage<T>(rows: T[], cursor: string | null | undefined, size = 25): CursorPage<T> {
  const start = decodeCursor(cursor);
  const items = rows.slice(start, start + size);
  return { items, next_cursor: start + size < rows.length ? encodeCursor(start + size) : null, page_size: size };
}

export function createAgentMockApi(
  data: MockFixtures,
  currentUser: () => MockUser,
  wait: () => Promise<void>,
): AgentMethods {
  const enabled = new Map(MOCK_SPECS.map((s) => [s.key, true]));
  let llmEnabled = true;
  let configVersion = 3;
  const history: ToggleEventDTO[] = [
    {
      config_version: 1,
      agent_key: null,
      enabled: true,
      previous_enabled: null,
      reason: "Initial configuration (all agents on)",
      updated_by: null,
      created_at: "2026-11-01T18:00:00Z",
      is_demo: false,
    },
    {
      config_version: 2,
      agent_key: "related_product",
      enabled: false,
      previous_enabled: true,
      reason: "Basket data being re-cleaned after a POS export bug",
      updated_by: "Super Admin",
      created_at: "2026-11-02T10:15:00Z",
      is_demo: true,
    },
    {
      config_version: 3,
      agent_key: "related_product",
      enabled: true,
      previous_enabled: false,
      reason: "Basket data fixed and verified",
      updated_by: "Super Admin",
      created_at: "2026-11-02T16:40:00Z",
      is_demo: true,
    },
  ];

  const requireAdmin = () => {
    if (currentUser().role !== "SUPER_ADMIN") throw new ApiError(403, "FORBIDDEN", "Super Admin only");
  };
  const specOf = (key: string) => {
    const spec = MOCK_SPECS.find((s) => s.key === key);
    if (!spec) throw new ApiError(404, "NOT_FOUND", `Unknown agent ${key}`);
    return spec;
  };

  // --- run history: 3 nightly runs (one with a skipped stage, one failed-then-retried) + one dry run --------------
  const runs: MockRun[] = [];
  const latest = Date.parse(data.latest_run.finished_at);
  const day = 86_400_000;
  const nightly = (
    n: number,
    status: RunStatus,
    stageStatus: (key: string) => { status: RunStatus; retries?: number; error?: string },
  ) => {
    const start = latest - n * day - 60_000;
    const runId = `00000000-0000-4000-8000-00000000000${n}`;
    const runDate = new Date(Date.parse(data.latest_run.run_date) - n * day).toISOString().slice(0, 10);
    runs.push({
      run_id: runId,
      parent_run_id: null,
      agent_key: null,
      agent_name: "nightly",
      trigger_type: "NIGHTLY",
      mode: "LIVE",
      status,
      run_date: runDate,
      started_at: iso(start),
      finished_at: iso(start, 58_000),
      duration_ms: 58_000,
      tool_calls: 3,
      llm_calls: 0,
      tokens: 0,
      est_cost_usd: "0.000000",
      retries: 0,
      stop_reason: status === "SUCCESS" ? "completed" : "completed with partial results",
      error: null,
      triggered_by: null,
      reason: null,
      input_ref: { run_date: runDate },
      config_version: n === 1 ? 2 : 3,
      is_demo: false,
    });
    let t = start + 1_000;
    PIPELINE_ORDER.forEach((key, i) => {
      const spec = specOf(key);
      const st = stageStatus(key);
      const skipped = st.status.startsWith("SKIPPED");
      const llm = spec.kind === "LLM" && !skipped;
      const dur = skipped ? 0 : 1_500 + i * 900;
      runs.push({
        run_id: `${runId.slice(0, -4)}${n}${String(i).padStart(3, "0")}`,
        parent_run_id: runId,
        agent_key: key,
        agent_name: spec.name,
        trigger_type: "NIGHTLY",
        mode: "LIVE",
        status: st.status,
        run_date: runDate,
        started_at: iso(t),
        finished_at: iso(t, dur),
        duration_ms: dur,
        tool_calls: skipped ? 0 : 2 + (i % 3),
        llm_calls: llm ? 2 : 0,
        tokens: llm ? 3_400 + i * 120 : 0,
        est_cost_usd: llm ? "0.001150" : "0.000000",
        retries: st.retries ?? 0,
        stop_reason: skipped ? st.status.toLowerCase() : llm ? "submit tool called" : "completed",
        error: st.error ?? null,
        triggered_by: null,
        reason: null,
        input_ref: { run_date: runDate },
        config_version: n === 1 ? 2 : 3,
        is_demo: false,
      });
      t += dur + 200;
    });
  };
  nightly(0, "SUCCESS", () => ({ status: "SUCCESS" }));
  runs.push({
    run_id: "00000000-0000-4000-8000-0000000000d1",
    parent_run_id: null,
    agent_key: "stock_balancing",
    agent_name: "Manual: Stock Balancing",
    trigger_type: "MANUAL_DRY_RUN",
    mode: "DRY_RUN",
    status: "SUCCESS",
    run_date: data.latest_run.run_date,
    started_at: iso(latest - 3_600_000),
    finished_at: iso(latest - 3_597_600),
    duration_ms: 2_400,
    tool_calls: 3,
    llm_calls: 0,
    tokens: 0,
    est_cost_usd: "0.000000",
    retries: 0,
    stop_reason: "completed",
    error: null,
    triggered_by: "Super Admin",
    reason: "Demo: preview tonight's balancing",
    input_ref: { agent_key: "stock_balancing" },
    config_version: 3,
    is_demo: true,
  });
  nightly(1, "PARTIAL", (k) =>
    k === "related_product"
      ? { status: "SKIPPED_DISABLED" }
      : k === "data_quality"
        ? { status: "SKIPPED_DEPENDENCY" }
        : { status: "SUCCESS" },
  );
  nightly(2, "PARTIAL", (k) =>
    k === "freshness"
      ? { status: "SUCCESS", retries: 1, error: null as unknown as undefined }
      : k === "sales_analytics"
        ? { status: "FAILED", error: "TimeoutError: statement timeout on lost-sales query" }
        : { status: "SUCCESS" },
  );
  runs.sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));

  // --- decisions from fixture recommendations ----------------------------------------------------------------------
  const latestNightly = runs.find((r) => r.parent_run_id === null) as MockRun;
  const typeOf: Record<string, [string, string]> = {
    TRANSFER: ["stock_balancing", "TRANSFER_CHOSEN_OVER_PO"],
    REORDER: ["stock_balancing", "PO_NEED_CREATED"],
    CO_REPLENISH: ["stock_balancing", "CO_REPLENISH_LINKED"],
    EXPIRY_ALERT: ["freshness", "EXPIRY_ALERT_RAISED"],
    ASSORTMENT_GAP: ["related_product", "ASSORTMENT_GAP_FOUND"],
    MARKDOWN: ["freshness", "EXPIRY_ALERT_RAISED"],
  };
  const outcomeOf = (status: string): AgentDecisionDTO["outcome"] =>
    status === "ACCEPTED"
      ? "ACCEPTED"
      : status === "EDITED"
        ? "EDITED"
        : status === "REJECTED"
          ? "REJECTED"
          : status === "SUPERSEDED"
            ? "SUPERSEDED"
            : "PENDING";
  const decisions: AgentDecisionDTO[] = data.recommendations.map((rec, i) => {
    const [agentKey, decisionType] =
      rec.status === "NEEDS_REVIEW" ? ["stock_balancing", "NEEDS_REVIEW_RAISED"] : typeOf[rec.rec_type]!;
    return {
      decision_id: `dec-${i}`,
      run_id: latestNightly.run_id,
      agent_key: agentKey,
      agent_name: specOf(agentKey).name,
      decision_type: decisionType,
      mode: "LIVE",
      store: rec.store,
      product: rec.product,
      summary: `${rec.rec_type.replace("_", " ").toLowerCase()} of ${rec.qty} × ${rec.product.name} for ${rec.store.name}`,
      rec_id: rec.rec_id,
      transfer_id: null,
      po_id: null,
      draft_id: null,
      evidence_ref: { rec_id: rec.rec_id },
      outcome: outcomeOf(rec.status),
      outcome_reason: rec.status === "REJECTED" ? "Shelf space not available" : null,
      outcome_at: rec.status === "PENDING" ? null : rec.created_at,
      created_at: rec.created_at,
      is_demo: false,
    };
  });
  decisions.push(
    {
      decision_id: "dec-coord",
      run_id: latestNightly.run_id,
      agent_key: "run_coordinator",
      agent_name: "Run Coordinator",
      decision_type: "COORDINATOR_INVOKE",
      mode: "LIVE",
      store: null,
      product: null,
      summary: "Invoked Replenishment Action for 2 NEEDS_REVIEW recommendations",
      rec_id: null,
      transfer_id: null,
      po_id: null,
      draft_id: null,
      evidence_ref: { needs_review: 2 },
      outcome: "NOT_APPLICABLE",
      outcome_reason: null,
      outcome_at: null,
      created_at: latestNightly.finished_at ?? latestNightly.started_at,
      is_demo: false,
    },
    {
      decision_id: "dec-review",
      run_id: latestNightly.run_id,
      agent_key: "recommendation_reviewer",
      agent_name: "Recommendation Reviewer",
      decision_type: "REVIEWER_FLAGGED",
      mode: "LIVE",
      store: data.recommendations[0]?.store ?? null,
      product: data.recommendations[0]?.product ?? null,
      summary: "Explanation mentions a quantity not in the evidence",
      rec_id: data.recommendations[0]?.rec_id ?? null,
      transfer_id: null,
      po_id: null,
      draft_id: null,
      evidence_ref: { check: "numbers_in_evidence" },
      outcome: "PENDING",
      outcome_reason: null,
      outcome_at: null,
      created_at: latestNightly.finished_at ?? latestNightly.started_at,
      is_demo: false,
    },
  );
  decisions.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

  const findRun = (runId: string) => {
    const run = runs.find((r) => r.run_id === runId);
    if (!run) throw new ApiError(404, "NOT_FOUND", "Agent run not found");
    return run;
  };
  const toItem = (r: MockRun): AgentRunItemDTO => {
    const { input_ref: _input, config_version: _cv, ...item } = r;
    void _input;
    void _cv;
    return item;
  };

  const summaryOf = (spec: Spec): AgentSummaryDTO => {
    const own = runs.filter((r) => r.agent_key === spec.key && r.parent_run_id !== null);
    const finished = own.filter((r) => r.status !== "RUNNING" && !r.status.startsWith("SKIPPED"));
    const mine = decisions.filter((d) => d.agent_key === spec.key);
    const decided = mine.filter((d) => ["ACCEPTED", "EDITED", "REJECTED"].includes(d.outcome));
    const last = own[0];
    return {
      agent_key: spec.key,
      name: spec.name,
      group: spec.group,
      kind: spec.kind,
      pattern: spec.pattern,
      critical: spec.critical,
      purpose: spec.purpose,
      enabled: enabled.get(spec.key) ?? true,
      effective_enabled: (enabled.get(spec.key) ?? true) && (spec.kind !== "LLM" || llmEnabled),
      depends_on: spec.depends_on,
      optional_inputs: spec.optional_inputs,
      triggerable: spec.triggerable,
      last_run: last
        ? { run_id: last.run_id, status: last.status, started_at: last.started_at, finished_at: last.finished_at }
        : null,
      runs_7d: own.length,
      success_rate_7d: finished.length ? finished.filter((r) => r.status === "SUCCESS").length / finished.length : null,
      p95_latency_ms: finished.length ? Math.max(...finished.map((r) => r.duration_ms ?? 0)) : null,
      tokens_7d: own.reduce((s, r) => s + r.tokens, 0),
      est_cost_7d_usd: (own.reduce((s, r) => s + Number(r.est_cost_usd), 0) || 0).toFixed(6),
      recommendations_7d: mine.filter((d) => d.rec_id).length,
      acceptance_rate: decided.length ? decided.filter((d) => d.outcome !== "REJECTED").length / decided.length : null,
    };
  };

  const pausedBanner = () => {
    const off = MOCK_SPECS.find((s) => s.critical && !enabled.get(s.key));
    if (!off) return null;
    const ev = [...history].reverse().find((h) => h.agent_key === off.key);
    return `Replenishment paused by ${ev?.updated_by ?? "Super Admin"}: ${ev?.reason ?? off.name + " is off"}`;
  };

  const listAgents = () => ({
    items: MOCK_SPECS.map(summaryOf),
    llm_enabled: llmEnabled,
    config_version: configVersion,
    paused_banner: pausedBanner(),
  });

  const detailOf = (key: string): AgentDetailDTO => {
    const spec = specOf(key);
    return {
      agent: summaryOf(spec),
      delegation:
        spec.kind === "LLM"
          ? "Delegated to an LLM agent: the task needs judgement about which approved tools to call."
          : "Not delegated to an LLM: the stage is a deterministic calculation.",
      description: `Agent card docs/agents/${key}.md`,
      discernment: "Code checks on every output; evaluation set in backend/tests/agent_evals.",
      diligence: "No tool can approve, submit, dispatch or change stock.",
      input_contract: "RunContext",
      output_contract: spec.decision_types.join(", ") || "KPIs / forecasts",
      read_tools: spec.read_tools,
      draft_tools: spec.draft_tools,
      stopping:
        spec.kind === "LLM"
          ? { max_tool_calls: 6, max_tokens: 12_000, timeout_s: 45, other: ["submit tool called"] }
          : { max_tool_calls: null, max_tokens: null, timeout_s: null, other: ["RunParams.max_steps per stage"] },
      prompt_version: spec.prompt_version,
      prompt_text: spec.prompt_version ? `# ${spec.name} — ${spec.prompt_version}\nUse only tool results.` : null,
      business_rules: key === "stock_balancing" ? [{ key: "order_fixed_cost", value: "250.00" }] : [],
      disabled_effect: spec.disabled_effect,
      human_in_the_loop: "Through the existing approvals.",
      decision_types: spec.decision_types,
      card_markdown: `# ${spec.name}\n\n${spec.purpose}\n\n## Allowed tools\n- ${spec.read_tools.join("\n- ")}`,
      toggle_history: history.filter((h) => h.agent_key === key || h.agent_key === null).reverse(),
      evals:
        spec.kind === "LLM"
          ? [
              {
                agent_key: key,
                source: "RECORDED",
                variant: "AGENT",
                cases: 12,
                correctness: 0.92,
                groundedness: 0.96,
                tool_use: 0.92,
                failure_handling: 1,
                latency_p50_ms: 2_400,
                latency_p95_ms: 5_900,
                tokens: 41_000,
                est_cost_usd: "0.012400",
                human_agreement: 0.9,
                created_at: "2026-11-05T09:00:00Z",
              },
              {
                agent_key: key,
                source: "RECORDED",
                variant: "BASELINE",
                cases: 12,
                correctness: 0.67,
                groundedness: 1,
                tool_use: 1,
                failure_handling: 1,
                latency_p50_ms: 40,
                latency_p95_ms: 90,
                tokens: 0,
                est_cost_usd: "0.000000",
                human_agreement: null,
                created_at: "2026-11-05T09:00:00Z",
              },
            ]
          : [],
    };
  };

  const stagesOf = (root: MockRun): PipelineStageDTO[] => {
    const children = runs.filter((r) => r.parent_run_id === root.run_id);
    return children
      .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))
      .map((c) => ({
        agent_key: c.agent_key ?? "",
        name: c.agent_name,
        status: c.status,
        run_id: c.run_id,
        duration_ms: c.duration_ms,
        retries: c.retries,
        outputs: c.status === "SUCCESS" ? c.tool_calls * 7 : null,
        error: c.error,
      }));
  };

  const pipelineOf = (root: MockRun): PipelineRunDTO => ({
    run_id: root.run_id,
    run_date: root.run_date,
    agent_key: root.agent_key,
    trigger_type: root.trigger_type,
    mode: root.mode,
    status: root.status,
    started_at: root.started_at,
    finished_at: root.finished_at,
    duration_ms: root.duration_ms,
    config_version: root.config_version,
    triggered_by: root.triggered_by,
    reason: root.reason,
    stop_reason: root.stop_reason,
    stages: stagesOf(root),
    escalations: stagesOf(root).some((s) => s.status === "FAILED") ? 1 : 0,
    has_partial: root.status === "PARTIAL",
    is_demo: root.is_demo,
  });

  return {
    async listAgents() {
      await wait();
      requireAdmin();
      return listAgents();
    },
    async getAgent(key) {
      await wait();
      requireAdmin();
      return detailOf(key);
    },
    async toggleAgent(key, body) {
      await wait();
      requireAdmin();
      const spec = specOf(key);
      if (body.reason.trim().length < 5) throw new ApiError(422, "VALIDATION", "A reason is required");
      if (spec.critical && !body.enabled && !body.confirm_critical) {
        throw new ApiError(422, "VALIDATION", "Turning off a critical agent needs a second confirmation");
      }
      const previous = enabled.get(key) ?? true;
      enabled.set(key, body.enabled);
      configVersion += 1;
      history.push({
        config_version: configVersion,
        agent_key: key,
        enabled: body.enabled,
        previous_enabled: previous,
        reason: body.reason,
        updated_by: currentUser().name,
        created_at: new Date().toISOString(),
        is_demo: false,
      });
      return detailOf(key);
    },
    async toggleLlmAgents(body) {
      await wait();
      requireAdmin();
      const previous = llmEnabled;
      llmEnabled = body.enabled;
      configVersion += 1;
      history.push({
        config_version: configVersion,
        agent_key: null,
        enabled: body.enabled,
        previous_enabled: previous,
        reason: body.reason,
        updated_by: currentUser().name,
        created_at: new Date().toISOString(),
        is_demo: false,
      });
      return listAgents();
    },
    async getAgentStats(key) {
      await wait();
      requireAdmin();
      specOf(key);
      const own = runs.filter((r) => r.agent_key === key);
      const byDay = new Map<string, { success: number; failed: number; other: number }>();
      for (const r of own) {
        const d = r.started_at.slice(0, 10);
        const e = byDay.get(d) ?? { success: 0, failed: 0, other: 0 };
        if (r.status === "SUCCESS") e.success += 1;
        else if (r.status === "FAILED") e.failed += 1;
        else e.other += 1;
        byDay.set(d, e);
      }
      return {
        agent_key: key,
        runs_by_day: [...byDay.entries()].sort().map(([d, e]) => ({ day: d, ...e })),
        latency_p50_ms: own.length ? (own[Math.floor(own.length / 2)]?.duration_ms ?? null) : null,
        latency_p95_ms: own.length ? Math.max(...own.map((r) => r.duration_ms ?? 0)) : null,
        decisions_by_type: [],
      };
    },
    async getTriggerPreview(key, mode) {
      await wait();
      requireAdmin();
      const spec = specOf(key);
      const off = !(enabled.get(key) ?? true) || (spec.kind === "LLM" && !llmEnabled);
      const running = runs.some((r) => r.status === "RUNNING" && r.parent_run_id === null);
      const downstream = MOCK_SPECS.filter((s) => s.depends_on.includes(key)).map((s) => s.key);
      return {
        agent_key: key,
        mode,
        allowed: spec.triggerable && !off && !running,
        blocked_reason: !spec.triggerable
          ? "This agent is triggered by questions on the Ask RetailPilot page"
          : off
            ? "The agent is disabled"
            : running
              ? "A run is in progress"
              : null,
        upstream: spec.depends_on.map((d) => ({ agent_key: d, fresh: true, action: "REUSE" as const })),
        downstream,
        recommendations_to_supersede: mode === "LIVE" ? decisions.filter((d) => d.agent_key === key).length : 0,
        live_triggers_last_hour: 0,
        live_trigger_limit: 3,
        consequences:
          mode === "LIVE"
            ? [
                `Pending recommendations of ${spec.name} from earlier runs are superseded`,
                downstream.length
                  ? `Downstream agents re-run: ${downstream.join(", ")}`
                  : "No downstream agent re-runs",
                "New outputs reach the inbox, POs and transfers like a nightly stage",
              ]
            : ["Outputs are stored in a preview set only — inbox, POs, transfers and dashboards do not change"],
      };
    },
    async triggerAgent(key, body) {
      await wait();
      requireAdmin();
      const spec = specOf(key);
      if (!spec.triggerable) throw new ApiError(409, "CONFLICT", "This agent cannot be triggered manually");
      if (!(enabled.get(key) ?? true)) throw new ApiError(409, "CONFLICT", "The agent is disabled");
      if (body.mode === "LIVE" && (!body.reason || !body.confirm)) {
        throw new ApiError(422, "VALIDATION", "A live run needs a reason and confirmation");
      }
      const now = Date.now();
      const runId = `manual-${runs.length}`;
      const run: MockRun = {
        run_id: runId,
        parent_run_id: null,
        agent_key: key,
        agent_name: `manual:${key}`,
        trigger_type: body.mode === "LIVE" ? "MANUAL_LIVE" : "MANUAL_DRY_RUN",
        mode: body.mode ?? "DRY_RUN",
        status: "SUCCESS",
        run_date: data.latest_run.run_date,
        started_at: iso(now),
        finished_at: iso(now, 2_100),
        duration_ms: 2_100,
        tool_calls: 2,
        llm_calls: spec.kind === "LLM" ? 2 : 0,
        tokens: spec.kind === "LLM" ? 2_800 : 0,
        est_cost_usd: spec.kind === "LLM" ? "0.000900" : "0.000000",
        retries: 0,
        stop_reason: "completed",
        error: null,
        triggered_by: currentUser().name,
        reason: body.reason ?? null,
        input_ref: { agent_key: key },
        config_version: configVersion,
        is_demo: false,
      };
      runs.unshift({ ...run, run_id: `${runId}-0`, parent_run_id: runId, agent_name: spec.name, triggered_by: null });
      runs.unshift(run);
      return { run_id: runId, mode: run.mode, status: run.status, message: `${spec.name}: ${run.mode} run finished` };
    },
    async listAgentRuns(query) {
      await wait();
      requireAdmin();
      const rows = runs
        .filter((r) => !query.agent_key || r.agent_key === query.agent_key)
        .filter((r) => !query.status || r.status === query.status)
        .filter((r) => !query.trigger_type || r.trigger_type === query.trigger_type)
        .filter((r) => !query.roots_only || r.parent_run_id === null)
        .map(toItem);
      return cursorPage(rows, query.cursor, query.page_size ?? 25);
    },
    async getAgentRun(runId) {
      await wait();
      requireAdmin();
      const run = findRun(runId);
      const children = runs.filter((r) => r.parent_run_id === runId).map(toItem);
      const steps: TraceStepDTO[] =
        children.length > 0
          ? children.map((c) => ({
              kind: "CHILD_RUN",
              at: c.started_at,
              name: c.agent_name,
              status: c.status,
              duration_ms: c.duration_ms,
              run_id: c.run_id,
            }))
          : [
              {
                kind: "TOOL",
                at: run.started_at,
                name: run.agent_key === "ask_retailpilot" ? "search_records" : "get_run_log",
                status: "OK",
                duration_ms: 34,
                args_summary: '{"query": "butter"}',
                result_summary: "3 records",
              },
              ...(run.llm_calls
                ? [
                    {
                      kind: "LLM" as const,
                      at: run.started_at,
                      name: "chat completion",
                      status: "OK",
                      duration_ms: 1_800,
                      model: "openai/gpt-oss-120b",
                      input_tokens: 2_100,
                      output_tokens: 700,
                      est_cost_usd: "0.000735",
                    },
                  ]
                : []),
              ...(run.error
                ? [
                    {
                      kind: "ERROR" as const,
                      at: run.finished_at ?? run.started_at,
                      name: "error",
                      status: "ERROR",
                      result_summary: run.error,
                    },
                  ]
                : []),
              {
                kind: "STOP",
                at: run.finished_at ?? run.started_at,
                name: "stop",
                status: run.status,
                result_summary: run.stop_reason,
              },
            ];
      const trace: AgentRunTraceDTO = {
        run: toItem(run),
        input_ref: run.input_ref,
        output_summary: { status: run.status },
        config_version: run.config_version,
        config_snapshot: Object.fromEntries(MOCK_SPECS.map((s) => [s.key, enabled.get(s.key) ?? true])),
        children,
        steps,
        previews:
          run.mode === "DRY_RUN"
            ? [
                {
                  agent_key: run.agent_key ?? "",
                  output_type: "RECOMMENDATION",
                  payload: { qty: 24, rec_type: "TRANSFER" },
                },
              ]
            : [],
        decisions: decisions.filter((d) => d.run_id === runId).length,
      };
      return trace;
    },
    async cancelAgentRun(runId) {
      await wait();
      requireAdmin();
      const run = findRun(runId);
      if (run.status !== "RUNNING") throw new ApiError(409, "CONFLICT", "Only a running run can be cancelled");
      run.stop_reason = "cancel requested";
      return toItem(run);
    },
    async listDecisions(query) {
      await wait();
      requireAdmin();
      const q = query.q?.trim().toLowerCase();
      const rows = decisions
        .filter((d) => !query.agent_key || d.agent_key === query.agent_key)
        .filter((d) => !query.decision_type || d.decision_type === query.decision_type)
        .filter((d) => !query.outcome || d.outcome === query.outcome)
        .filter((d) => !query.store_id || d.store?.store_id === query.store_id)
        .filter((d) => !query.mode || d.mode === query.mode)
        .filter((d) => !query.run_id || d.run_id === query.run_id)
        .filter((d) => !q || `${d.summary} ${d.product?.name ?? ""}`.toLowerCase().includes(q));
      return cursorPage(rows, query.cursor, query.page_size ?? 25);
    },
    async getDecisionStats(agentKey) {
      await wait();
      requireAdmin();
      const groups = new Map<string, DecisionStatDTO>();
      for (const d of decisions.filter((x) => !agentKey || x.agent_key === agentKey)) {
        const k = `${d.agent_key}|${d.decision_type}`;
        const g = groups.get(k) ?? {
          agent_key: d.agent_key,
          decision_type: d.decision_type,
          total: 0,
          accepted: 0,
          edited: 0,
          rejected: 0,
          pending: 0,
          superseded: 0,
          acceptance_rate: null,
        };
        g.total += 1;
        if (d.outcome === "ACCEPTED") g.accepted += 1;
        if (d.outcome === "EDITED") g.edited += 1;
        if (d.outcome === "REJECTED") g.rejected += 1;
        if (d.outcome === "PENDING") g.pending += 1;
        if (d.outcome === "SUPERSEDED") g.superseded += 1;
        const decided = g.accepted + g.edited + g.rejected;
        g.acceptance_rate = decided ? (g.accepted + g.edited) / decided : null;
        groups.set(k, g);
      }
      return [...groups.values()];
    },
    async listPipelineRuns(query) {
      await wait();
      requireAdmin();
      const rows = runs
        .filter((r) => r.parent_run_id === null)
        .filter((r) => !query.trigger_type || r.trigger_type === query.trigger_type)
        .filter((r) => !query.status || r.status === query.status)
        .map(pipelineOf);
      return cursorPage(rows, query.cursor, query.page_size ?? 20);
    },
    async getRunGraph(runId) {
      await wait();
      requireAdmin();
      const root =
        runId === "latest"
          ? runs.find((r) => r.parent_run_id === null && r.trigger_type === "NIGHTLY")
          : findRun(runId);
      if (!root) throw new ApiError(404, "NOT_FOUND", "No runs yet");
      const children = runs.filter((r) => r.parent_run_id === root.run_id);
      const pending = decisions.some((d) => d.outcome === "PENDING");
      const nodes: GraphNodeDTO[] = GRAPH_LAYOUT.map((n) => {
        const child = n.agent_key ? children.find((c) => c.agent_key === n.agent_key) : undefined;
        return {
          ...n,
          status:
            n.node_type === "GATE"
              ? pending
                ? "WAITING"
                : "DONE"
              : n.node_type === "AGENT"
                ? (child?.status ?? "NOT_RUN")
                : "DONE",
          run_id: child?.run_id ?? null,
          detail: child ? `${child.duration_ms ?? 0} ms · ${child.tool_calls} tool calls` : null,
        };
      });
      const graph: RunGraphDTO = {
        run_id: root.run_id,
        status: root.status,
        in_progress: root.status === "RUNNING",
        nodes,
        edges: GRAPH_EDGES,
      };
      return graph;
    },
    async getAgentStatus() {
      await wait();
      currentUser();
      return {
        expiry_checks_on: enabled.get("freshness") ?? true,
        reviewer_on: (enabled.get("recommendation_reviewer") ?? true) && llmEnabled,
        ask_enabled: (enabled.get("ask_retailpilot") ?? true) && llmEnabled,
        replenishment_paused: pausedBanner(),
      };
    },
    async getAssistantStatus() {
      await wait();
      currentUser();
      return {
        enabled: (enabled.get("ask_retailpilot") ?? true) && llmEnabled,
        examples: ["Why are we ordering butter?", "What did Store A transfer this week?", "What is the L2 threshold?"],
      };
    },
    async ask(question) {
      await wait();
      const user = currentUser();
      if (!(enabled.get("ask_retailpilot") ?? true) || !llmEnabled) {
        throw new ApiError(409, "CONFLICT", "Ask RetailPilot is disabled");
      }
      const text = question.toLowerCase();
      if (/\b(approve|submit|dispatch|delete|change stock)\b/.test(text)) {
        return {
          answer: "I can only read and explain. Approvals and stock changes are done by people in the app.",
          found: false,
          refused: true,
          citations: [],
          run_id: null,
          latency_ms: 40,
          mode: "LLM",
        };
      }
      const visible = data.recommendations.filter(
        (r) => user.role === "SUPER_ADMIN" || r.store.store_id === user.store_id,
      );
      const hits = visible.filter((r) => text.includes(r.product.name.toLowerCase().split(" ")[0] ?? "~")).slice(0, 3);
      if (hits.length === 0) {
        return {
          answer: "I could not find this in the recommendations, rules or policies you can see.",
          found: false,
          refused: false,
          citations: [],
          run_id: null,
          latency_ms: 60,
          mode: "LLM",
        };
      }
      return {
        answer: hits
          .map((h) => `${h.store.name}: ${h.rec_type.toLowerCase()} of ${h.qty} × ${h.product.name}.`)
          .join(" "),
        found: true,
        refused: false,
        citations: hits.map((h) => ({
          source_type: "RECOMMENDATION" as const,
          source_id: h.rec_id,
          label: `${h.product.name} — ${h.store.name}`,
        })),
        run_id: null,
        latency_ms: 80,
        mode: "LLM",
      };
    },
  };
}
