# Build order — prompts to paste into Claude Code

Rules for every phase
- Start a fresh session per phase (`/clear`). Claude reads CLAUDE.md automatically.
- Switch to plan mode first, review the plan, then let it implement.
- Review every diff. Run the checks. Commit at the end of the phase: `git commit -m "phase N: …"`.
- If Claude wants to change a business rule, a dependency or the schema outside a migration — stop and decide yourself.

---

## Phase 0 — Orientation (no code)
```
Read CLAUDE.md, docs/01-business-requirements-v2.2.md (sections 5–10, 16–17),
docs/02-technical-spec.md, docs/03-design-system.md and docs/04-demo-scenarios.md.
Skim the PlantUML files in docs/diagrams/ (cd1–cd4 for structure, sd01–sd15 for flows).
Do not write code. Reply with:
1) a one-page summary of the system in your own words,
2) any contradictions or gaps you find between the docs and diagrams,
3) the questions you need answered before Phase 1.
```

## Phase 1 — Repository scaffold
```
Create the monorepo exactly as in CLAUDE.md "Repository layout":
- infra/docker-compose.yml with postgres:16 and redis:7 (named volumes, healthchecks), .env.example
- backend: uv project (Python 3.12) with fastapi, uvicorn, pydantic v2, pydantic-settings, sqlalchemy 2,
  alembic, psycopg[binary], redis, celery, pandas, numpy, mlxtend, python-jose or pyjwt, passlib,
  anthropic; dev: pytest, pytest-asyncio, httpx, ruff, mypy, factory-boy
- app/main.py with /health, core/config.py (settings from env), core/errors.py (error format from spec §5),
  core/logging.py, workers/celery_app.py with an empty beat schedule
- frontend: Vite React TS app with TanStack Query, TanStack Table, React Router, Recharts, Tailwind,
  openapi-typescript; scripts dev, build, lint, typecheck, gen:api
- root README.md with run instructions, .gitignore, pre-commit config (ruff, eslint)
Acceptance: docker compose up works; backend /health returns ok; frontend dev server starts;
`uv run pytest` and `npm run typecheck` pass. Show me the tree when done.
```

## Phase 2 — Database schema and migrations
```
Implement the SQLAlchemy models for every table in docs/02-technical-spec.md §10 using
docs/diagrams/cd1_domain_core.puml and cd2_domain_workflow.puml (v3) as the source.
Include: enums for all statuses (spec §2), UUID PKs, indexed FKs, NUMERIC(14,2) money, timestamps,
InventoryPosition with shelf_qty/backroom_qty, InventoryMovement ledger, SupplierStoreTerms, TransferRoute
(with handling cost), PurchaseOrder.parent_po_id and l1_deadline, POLine.line_status, Approval.level incl. DEST/DONOR.
Create the initial Alembic migration, monthly partitioning for sales_line and inventory_movement,
the materialized views mv_dashboard_store_day and mv_inbox_counts (with unique indexes),
and a seed for BusinessRule defaults (spec §9) and two roles of PoC users (1 Super Admin, 1 supervisor per store).
Skip extension tables' logic but create store_layout / shelf_location / supplier_scheme tables.
Acceptance: `alembic upgrade head` and `downgrade base` both work on a clean DB; a test asserts every table exists.
Also (D-35 … D-40): async API engine + separate sync worker engine in app/core/db.py; inventory_movement
occurred_at/business_date; indexes created on partitioned parents (test: a new partition inherits them);
pg_trgm GIN on product name/SKU; count_queries fixture; lazy="raise" relationships; GZip; response-model test.
```

## Phase 3 — Deterministic tools (test-first)
```
Implement app/tools/ as pure functions/classes with the exact signatures in spec §8:
RequirementCalculator, CostModel, TransferDecisionEngine (decide, find_expiry_receivers),
LostSalesCalculator, POBuilder (select_supplier, consolidate, round_to_pack, validate,
prioritise_within_budget, apply_edits, split), ForecastTools (classify_abc_xyz, baseline_avg_daily only),
BasketTools (clean_bills, to_basket_matrix, mine_rules with mlxtend fpgrowth, detect_substitutes,
find_assortment_gaps). Follow docs/diagrams/sd07_transfer_decide.puml step by step.
Write the unit tests FIRST, including: the worked example (40 / 24 / 16), "sells high in every store → PO only",
donor protection, no route, transfer slower than lead time, incremental-cost comparison excluding purchase price,
per-store demand windows (A 3+2, B 7+2, C 5+3), lost revenue vs lost profit, pack/MOQ rounding, budget trimming,
PO split. Target 100% line coverage for app/tools.
Acceptance: `uv run pytest tests/unit -q` passes; `mypy app/tools --strict` clean.
```

## Phase 4 — Ledger, ingestion and synthetic data
```
Implement InventoryLedgerService (post, reconcile) and DataIngestionService.load_and_validate
following sd02_ingestion.puml. Stock changes ONLY via the ledger.
Then build data/synthetic/generate.py: 3 stores, ~300 SKUs across FMCG categories, 180 days of bill-level
sales with weekly seasonality and festival spikes, batches with expiry for perishables, suppliers with
per-store lead times, transfer routes, and the five scenarios of docs/04-demo-scenarios.md planted
deterministically (fixed seed). Output CSVs that a PosSource adapter reads.
Acceptance: ingestion loads the synthetic data; reconciliation test creates an ADJUSTMENT for a planted mismatch;
stale-SKU detection test passes.
Also (4b): bulk loads use PostgreSQL COPY into staging tables (D-41); backfill writes historical
inventory_movement.occurred_at; then run EXPLAIN (ANALYZE, BUFFERS) on the top-10 queries against the `full`
dataset and record the plans in docs/notes/query-plans.md (D-38).
```

## Phase 5 — Agents and orchestrator
```
Implement BaseAgent, RunContext, AgentResult, AgentRunLogger and WorkflowOrchestrator.run_nightly per
sd01_orchestration.puml (idempotency guard, retries, step cap, critical vs non-critical agents,
materialized-view refresh, cache swap with run-versioned keys). Implement the six agents per sd03–sd09.
ExplanationService uses the Anthropic SDK with model from env LLM_MODEL, temperature 0, batched, validates that
numbers in the text match evidence, and falls back to deterministic templates when the key is missing or output
is invalid. Register nightly_run_task and approval_deadline_task in Celery Beat.
Acceptance: `uv run pytest tests/scenarios` runs the pipeline on synthetic data and asserts the recommendation
outcomes of scenarios 1–5; agent_run/tool_call/decision_evidence rows exist for every agent.
Also: a Beat job that creates future monthly partitions of sales_line and inventory_movement before data reaches
the DEFAULT partition, and alerts if the default partition holds rows (D-35). Measure the nightly run on the `full`
dataset and propose its time limit (D-42). Workers use the sync engine (statement_timeout 10 min, D-36).
Windows note: Celery does not support Windows' default pool (prefork). Locally run the worker with `--pool=solo`;
also provide a Dockerfile and docker-compose service for the worker (Linux) so the production-like path is tested.
Plan this in Phase 5.
```

## Phase 6 — API, approvals, transfers, cache
```
Implement JWT auth with roles and store scoping (spec §4), then the endpoints in spec §5.
Follow sd10_po_approval.puml (line-level L1, deadline check, split, L2 on continuing PO, row locks),
sd14_approval_deadline.puml, sd12_transfer_execution.puml (accept → approve-release → re-check → dispatch →
receive, ledger postings, discrepancy), sd11_dashboard_cache.puml (cache-aside, fail-open) and
sd15_store_inventory_2d.puml. Cross-store data must be limited to store name + quantity for supervisors.
Acceptance: integration tests cover every edge case in docs/04-demo-scenarios.md; 403/404/409/422 return the
standard error body; OpenAPI spec exported to frontend/openapi.json.
Also: per list endpoint, an integration test that the query count does not grow with row count (D-39); list
queries select only DTO columns (D-40); cursor paging for movements (D-37).
```

## Phase 7 — Frontend shell and design system
```
Implement the design system from docs/03-design-system.md: tokens.css, Tailwind mapping, Inter font, and shared
components (AppShell with collapsible sidebar and header, KpiCard, StatusBadge with icon+label, DataTable built on
TanStack Table with sticky header/search/filters/sort/pagination/selection/column chooser/loading-empty-error states,
Button variants, Modal with confirmation pattern, Stepper, EvidencePanel, DeadlineCountdown).
Role-based navigation map from §5 (hide inaccessible items). Generate API types with `npm run gen:api`;
login page; store switcher and "Data as of last run" in the header.
Acceptance: Storybook-free component demo page renders all components; lint and typecheck pass;
no hex colours outside tokens.css (add an ESLint/grep check).
```

## Phase 8 — Screens
```
Build the screens in this order, each wired to the real API:
1) Store Inventory (2D) — columns: SKU, shelf, shelf min, backroom, incoming, reserved, available, own requirement,
   surplus/shortage, days of cover, stockout risk, near-expiry qty, pending transfers, refill-from-backroom flag;
   tabs: All products / Stock moves (ledger) / Batches / Expiring soon.
2) Recommendations inbox + Recommendation detail with EvidencePanel (spec in design doc §6).
3) Approval centre — line-level L1 for supervisors, L2 + escalations for Super Admin, deadline countdown,
   split PO view, reject-with-reason modal.
4) Stock transfers — list + stepper detail with accept / approve release / dispatch / receive actions.
5) Overview dashboards — Super Admin (business-wide KPIs incl. lost revenue and lost profit, store comparison,
   pending approvals, active transfers) and Store Supervisor (store KPIs, alerts, recommendations).
6) Purchase orders list/detail, Goods receipt, System monitoring (agent runs list + run trace).
Acceptance: walk through all five demo scenarios in the browser as the right users; record any gaps.
```

## Phase 9 — Hardening and demo
```
Add Playwright end-to-end tests for the five demo scenarios, a historical-replay script that runs the pipeline
for the last 28 days of synthetic data and reports forecast WMAPE and recommendation accuracy, seed/reset commands
for demos, and a docs/DEMO_SCRIPT.md. Fix all lint/type warnings. Produce a short gap list against
docs/01-business-requirements-v2.2.md section 9.
Also: k6 or Locust load test verifying p95 < 200 ms cached / < 500 ms uncached reads (D-42, spec §11).
```

## Later (only when asked): 3D twin (sd13), statsforecast models + calendar uplift, scheme slabs, markdown rules,
supplier scorecard, WhatsApp.
