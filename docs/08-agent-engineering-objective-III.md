# RetailPilot AI — Agent Engineering Brief (Objective III)

Place this file at `docs/08-agent-engineering-objective-III.md`. It is the source of truth for how the
manager will review the agent work. It ADDS an agent layer on top of the deterministic core; it does not
change any frozen business rule (CLAUDE.md rules 1–11 still hold).

> Implementation status (D-50, 2026-11-06): all five patterns are implemented — see the agent cards in
> `docs/agents/`, the evaluation report `docs/notes/agent-eval-report.md` and the comparison
> `docs/notes/agent-pattern-comparison.md`. The two exploration items are documented only
> (`docs/notes/managed-agents-and-vertex-exploration.md`); no prototype was built (no approval / GCP project).

## 1. What the reviewer measures
For every agent pattern:
- A defined purpose, input/output contract (Pydantic structured output), allowed tools and stopping condition.
- An evaluation set covering: normal, ambiguous, missing-data, invalid-input and tool-failure cases.
- Recorded metrics: correctness, groundedness, tool-use behaviour, failure handling, latency and cost, reviewer feedback.
- Proof that unsafe or consequential actions are blocked or routed to human approval.
- A written rationale: why this pattern, and why simpler application logic is or is not sufficient.
Topics to demonstrate: model instructions, structured outputs, tool calling, MCP, retrieval, orchestration,
state, memory, stopping conditions, human-in-the-loop review. Frame everything with the 4D framework:
Delegation, Description, Discernment, Diligence.

## 2. Honest starting point
Today the six "agents" (SalesAnalytics, DemandForecasting, RelatedProduct, StockBalancing, Freshness,
PurchaseOrder) are deterministic modules; the LLM only writes explanation text. That is correct for the
calculations and must stay that way: numbers always come from deterministic tools. Objective III needs
real LLM agents where an agent actually improves the workflow — agents that DECIDE which approved tools to
call and how to compose results, while tools do all calculation.

## 3. The five patterns mapped to RetailPilot

| # | Pattern | RetailPilot agent | Why an agent (Delegation) | Deterministic baseline to compare against |
|---|---|---|---|---|
| 1 | Research / retrieval | **Ask RetailPilot** — answers supervisor and admin questions ("Why are we ordering butter?", "What did Store A transfer this week?") by retrieving decision evidence, recommendations, business rules and SOP/policy text | Open-ended natural-language questions; must choose what to retrieve | Fixed recommendation detail screen (no Q&A) |
| 2 | Data analysis / validation | **Data Quality Agent** — triages ingestion results (stale SKUs, snapshot mismatches, anomalies from SD-02/SD-03), classifies likely cause, proposes NEEDS_REVIEW items with evidence | Interpreting mixed signals into a cause and next step | SD-02 rule-based flags only |
| 3 | Workflow / action with approval gates | **Replenishment Action Agent** — uses tools to assemble a transfer-or-PO proposal for an exception case (e.g. budget-trimmed or NEEDS_REVIEW lines), returns a structured draft; it can only CREATE DRAFTS, never approve or submit | Exception cases where rules alone leave a gap | Existing deterministic PurchaseOrderAgent + TransferDecisionEngine |
| 4 | Coordinator / orchestrator | **Run Coordinator** — after the deterministic nightly run, decides how to handle failures and exceptions within an allow-list: retry an agent, mark PARTIAL, escalate to Super Admin, or invoke agents 2/3/5 | Choosing among recovery paths from logs and context | Current deterministic WorkflowOrchestrator (SD-01) — keep it as the primary path; compare |
| 5 | Reviewer / evaluator | **Recommendation Reviewer** — checks each recommendation and draft before it reaches the inbox: groundedness of explanation vs evidence, policy compliance (donor protection, scoping, budget), flags issues; plus the offline evaluation harness (LLM-as-judge + code checks) | Judging quality of text and reasoning | Current number-match check in ExplanationService |

Exploration items (document, prototype only if access/approval permits):
- Claude Managed Agents: implement pattern 1 or 5 a second way and compare with the application-orchestrated version (setup effort, control, observability, cost, latency). Check current Anthropic docs and organisational approval first; do not assume features.
- GCP Vertex AI agent runtime: document how one agent (pattern 1 suggested) would be hosted, invoked, monitored and integrated with the FastAPI services; prototype only if a GCP project is approved.

## 4. Required design for every agent ("agent card")
Each agent gets `docs/agents/<name>.md` with:
- Purpose and 4D notes: Delegation (why an agent), Description (instructions + contracts), Discernment (how output is judged), Diligence (approvals, logging, accountability).
- System instructions (versioned prompt file in `backend/app/agents/llm/prompts/`).
- Input contract and output contract (Pydantic models; output validated, invalid output → retry once → fail safe).
- Allowed tools (explicit allow-list; read tools vs draft-write tools). NO tool may approve, submit, dispatch or change stock.
- State and memory: what the agent keeps within a run (scratchpad of tool results) and across runs (none by default; if any, stored in PostgreSQL and listed).
- Stopping conditions: max tool calls, max tokens, timeout, "answer found", and "cannot answer → say so with reason".
- Failure handling: tool error, empty data, invalid input, model error → each has a defined outcome.
- Human-in-the-loop: which outputs need approval and through which existing workflow (L1/L2, transfer acceptance).

## 5. Tools and MCP
- Expose approved read-only and draft-creation tools through an internal MCP server (`retailpilot-tools`), wrapping existing services/tools: e.g. `get_recommendation`, `get_evidence`, `get_inventory_position`, `get_business_rules`, `search_policies` (retrieval), `get_run_log`, `create_draft_recommendation`.
- Tools enforce role and store scoping from the calling user's context (rule 10) — the agent cannot widen access.
- Consequential operations (approve, submit PO, dispatch, receive, change rules, change stock) are NOT tools. Demonstrate in tests that an agent asked to do them refuses or produces a draft routed to approval.

## 6. Retrieval
- Corpus: decision evidence and recommendations (PostgreSQL), business rules, and a small set of SOP/policy documents (to be written as synthetic markdown in `data/policies/`).
- Use PostgreSQL full-text search first; add vector search (pgvector) only if evaluation shows FTS is insufficient — record the decision.
- Every answer cites its sources (record IDs or document sections); unanswerable questions return "not found" rather than guessing.

## 7. Evaluation (Discernment)
- `backend/tests/agent_evals/` with at least 10 cases per agent covering: normal, ambiguous, missing data, invalid input, tool failure (simulated), and prompt-injection/unsafe-request cases.
- Code-based checks: structured output validity, correct tool sequence, numbers equal tool results, scoping respected, blocked actions blocked.
- LLM-as-judge (separate prompt) for groundedness and answer quality, with a rubric; sample judged by a human reviewer and the agreement recorded.
- Record per run: correctness, groundedness, tool calls, failures handled, latency p50/p95, tokens and cost — stored via AgentRunLogger and summarised in `docs/notes/agent-eval-report.md`.
- Evals run without a live model in CI using recorded responses; live runs are manual and logged.

## 8. Comparison and rationale
`docs/notes/agent-pattern-comparison.md`: for each pattern, compare agent vs deterministic baseline on the same eval set (accuracy, groundedness, latency, cost, failure behaviour) and state the conclusion — where the agent earns its place and where application logic is sufficient. It is an acceptable and expected outcome that some agents are NOT adopted.

## 9. Applying 4D to our own use of Claude Code
Document in `docs/notes/4d-claude-code.md` how this project already applies 4D to the AI coding assistant:
Delegation (phase-by-phase scope), Description (CLAUDE.md, spec, diagrams, prompts), Discernment (plan review,
tests, property tests, screenshot checks, decision log), Diligence (explicit approval for rule changes,
local commits, no push without permission).

## 10. Placement in the build plan
- Phase 5a: deterministic nightly pipeline as already planned (unchanged).
- Phase 5b (new): MCP tool server, agent framework (instructions, structured output, tool loop, stopping conditions, logging), agents 2 and 4.
- Phase 6b (new, after approvals API): agents 1, 3 and 5, with approval routing.
- Phase 9: evaluation harness results, comparison document, Managed Agents and Vertex AI exploration notes.
