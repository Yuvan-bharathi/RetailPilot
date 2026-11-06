# RetailPilot AI — Agent Console (Agent Management, Logs, Decisions, Triggers, Pipeline, Visual Flow)

Place at `docs/09-agent-console.md`. Super Admin only. Replaces and extends the current "System monitoring"
nav item with an **Agents** section. It is also the main evidence screen for the Objective III review
(docs/08): it makes purpose, tools, stopping conditions, traceable evidence, failures and human approval visible.

> Implementation status (D-50, 2026-11-06): implemented as specified, with the refinements recorded in
> docs/05-decision-log.md D-50/D-51 (hand-built SVG instead of React Flow; manual-run data scoping; Ask RetailPilot
> also has its own page for both roles; the nightly trigger button moved to the Pipeline page).

## 1. Scope — every agent appears in one registry
| Group | Agents | Kind |
|---|---|---|
| Nightly pipeline | SalesAnalytics, DemandForecasting, RelatedProduct, StockBalancing, Freshness, PurchaseOrder | Deterministic (LLM only for explanations) |
| Objective III layer | Ask RetailPilot, Data Quality, Replenishment Action, Run Coordinator, Recommendation Reviewer | LLM tool-calling agents (docs/08) |
New agents are added by registering them, not by changing the screens.

## 2. Navigation (Super Admin)
Agents
- Overview — `/agents` (management + toggles)
- Pipeline — `/agents/pipeline` (runs over time, stage status)
- Visual flow — `/agents/flow` (graph of a selected run)
- Logs — `/agents/logs` (runs, tool calls, errors, LLM usage)
- Decisions — `/agents/decisions` (every decision taken, with evidence and outcome)
- Agent detail — `/agents/:agentKey` (card, config, runs, decisions, evals, trigger)
Store Supervisors do not see this section (hide, do not disable).

## 3. Pages
**3.1 Overview (management)** — one row/card per agent: name, pattern (retrieval / validation / action / coordinator / reviewer / pipeline stage), kind, enabled toggle, critical flag, dependencies, last run status and time, success rate (7 days), p95 latency, tokens and cost (LLM agents), recommendations produced, acceptance rate of its recommendations. Global switch: "All LLM agents" on/off (cost and safety kill switch).

**3.2 Agent detail** — the agent card from docs/agents/<name>.md rendered: purpose, 4D notes, input/output contract, allowed tools (read vs draft-write), stopping conditions, prompt version (LLM), parameters (read-only here; edited through Settings → business rules); recent runs; recent decisions; latest evaluation results (correctness, groundedness, failure handling); "Run now" panel (3.6); toggle history (who, when, why).

**3.3 Pipeline** — nightly runs as rows (date, status, duration, config version, trigger type); expanding a run shows each stage in order with status (success / partial / failed / skipped-disabled / skipped-dependency), duration, retries, outputs count. Highlights runs with escalations or partial results.

**3.4 Visual flow** — graph for a selected run: nodes = agents (and key tools), edges = data hand-offs (forecasts → stock balancing → PO; reviewer before inbox; coordinator on exceptions; human approval gates as explicit nodes). Node colour = status using semantic tokens + text label/icon. Click a node → that agent's run trace. Static layout (fixed positions per agent), not physics. Polls every 5 s while a run is in progress.

**3.5 Logs** — agent runs list (cursor paging; filters: agent, status, trigger type, date) → run trace: timeline of steps, tool calls (name, arguments summary, result summary, duration, status), LLM calls (model, tokens, cost, latency), retries, errors, stopping reason. Exportable as JSON.

**3.6 Per-agent trigger ("Run now")**
- Modes: **Dry run** (default) — runs on the latest data and stores outputs in a preview set that never reaches the inbox, POs or transfers; **Live** — publishes like a nightly stage.
- Live requires: Super Admin, confirmation modal stating consequences (which recommendations will be superseded, which downstream agents will re-run), and a reason.
- Dependencies: triggering an agent re-runs its required upstream inputs only if they are stale; downstream dependants are listed and re-run in live mode (or skipped in dry run).
- Blocked when: the agent is disabled, a nightly run is in progress (lock), or rate limit hit (default 3 live triggers per agent per hour).
- Every trigger is an AgentRun with trigger_type MANUAL_DRY_RUN or MANUAL_LIVE and the user/reason recorded.

**3.7 Decisions** — one row per decision taken by any agent: time, agent, decision type (e.g. TRANSFER_CHOSEN_OVER_PO, PO_NEED_CREATED, CO_REPLENISH_LINKED, EXPIRY_TRANSFER, SUPERSEDED, NEEDS_REVIEW_RAISED, REVIEWER_FLAGGED, COORDINATOR_RETRY / ESCALATE, ANSWER_GIVEN / NOT_FOUND), store, product, short summary, link to evidence, human outcome (accepted / edited / rejected with reason / pending). Filters and cursor paging. Shows acceptance rate per agent and decision type (feeds Objective III evaluation).

## 4. Toggle rules (on/off)
- Super Admin only; reason required; audited (who, when, old → new, reason); versioned config.
- Takes effect from the **next** run; a running run uses the config snapshot taken at its start (stored on the run).
- Effects when disabled:
| Agent off | Effect |
|---|---|
| SalesAnalytics | KPIs and lost revenue/profit not refreshed; screens show "as of <last run>" |
| DemandForecasting, StockBalancing, PurchaseOrder (critical) | Nightly replenishment **paused**: no new recommendations/POs, users keep last results, banner "Replenishment paused by <user>: <reason>"; double confirmation required |
| RelatedProduct | No co-replenishment / assortment gaps; StockBalancing runs without them and says so in evidence |
| Freshness | No expiry transfers or alerts; banner on inventory "Expiry checks off" |
| Recommendation Reviewer | Recommendations still reach the inbox, labelled "Not reviewed" |
| Run Coordinator | Deterministic orchestrator handles failures (current SD-01 behaviour) |
| Data Quality, Replenishment Action, Ask RetailPilot | Their features hidden or show "Agent disabled"; deterministic flows unaffected |
| All LLM agents (global) | All of the above LLM agents off; explanations fall back to templates |
- Toggles never stop or roll back an in-progress run; a separate "Cancel run" (Super Admin, confirmation) stops after the current step.

## 5. Backend (proposal for Claude Code to refine)
- Tables: `agent_definition` (registry: key, name, group, kind, pattern, critical, depends_on[], card path; seeded), `agent_config` (agent_key, enabled, config_version, updated_by, reason, updated_at; history kept), `agent_run` additions (trigger_type NIGHTLY | MANUAL_DRY_RUN | MANUAL_LIVE, config_version, triggered_by, reason, mode, stop_reason), `agent_decision` (decision log; references run, recommendation, evidence; outcome updated by approval/transfer workflows).
- Endpoints: `GET /agents`, `GET /agents/{key}`, `PATCH /agents/{key}` (enabled + reason), `PATCH /agents/llm` (global switch), `POST /agents/{key}/runs` (mode, reason), `POST /agent-runs/{id}/cancel`, `GET /agent-runs` (cursor), `GET /agent-runs/{id}` (trace), `GET /agent-decisions` (cursor), `GET /pipeline/runs` and `GET /pipeline/runs/{run_id}/graph` (nodes, edges, statuses), `GET /agents/{key}/stats`.
- Orchestrator reads `agent_config` at run start and snapshots it; disabled stages are recorded as SKIPPED_DISABLED; dependants of a disabled critical agent → run status PAUSED.
- Dry-run outputs go to preview tables/partition keyed by run_id with mode DRY_RUN and are excluded from inbox, POs, transfers, dashboards and cache.
- Performance (spec §11): cursor paging for runs, tool calls and decisions; indexes on (agent_key, started_at), (run_id), decision (agent_key, created_at), (outcome); cached stats per run.

## 6. Frontend
- Reuse design-system components (DataTable, StatusBadge, Stepper, Modal confirmation, EvidencePanel).
- Visual flow: React Flow (`@xyflow/react`, pinned) with fixed node positions — needs approval as a new dependency; otherwise a hand-built SVG with the same API.
- Status colours from semantic tokens only; every status has a text label and icon.

## 7. Tests and acceptance
- Toggle: permission (403 for supervisors), reason required (422), audit row written, effect only from next run, critical-agent pause behaviour, global LLM switch.
- Trigger: dry run never changes inbox/POs/transfers/cache; live requires confirmation + reason; blocked while nightly run in progress and when disabled; rate limit; dependency handling.
- Decisions: every recommendation/transfer/PO-need creation writes a decision row; outcome updated on approval/rejection.
- Visual flow and pipeline reflect a run with a skipped (disabled) stage and a failed-then-retried stage correctly.
- axe and keyboard checks on all agent pages; screenshot review in Chrome.

## 8. Placement
- Now: spec, contract (DTOs + 501 stubs), mock data and UI (read-only parts) — after the HLD/LLD docs.
- Phase 5: registry, config, toggles, run snapshots, decision logging, pipeline/graph endpoints, dry-run mode.
- Phase 5b/6b: Objective III agents appear in the console as they are built.
- Phase 9: load/perf checks for logs and decisions; evaluation results shown on agent detail.
