# RetailPilot AI — project instructions for Claude Code

AI replenishment platform for multi-store FMCG supermarkets: forecasts store-SKU demand,
restocks related products together, moves genuine surplus between own stores before buying,
and prepares purchase orders for human approval. Every agent decision is explained and logged.

## Source of truth (read the relevant file before working on an area)
- Business requirements (frozen v2.2): `docs/01-business-requirements-v2.2.md`
- Technical spec — formulas, functions, states, API, permissions: `docs/02-technical-spec.md`
- Design system (frozen v1.0) + UI rules: `docs/03-design-system.md`
- Demo scenarios and acceptance tests: `docs/04-demo-scenarios.md`
- Class and sequence diagrams (PlantUML, code level): `docs/diagrams/` (cd1–cd4, sd01–sd15)
- Build order and phase prompts: `PROMPTS.md`
If code and docs disagree, follow the docs and tell me. Never silently change a business rule.

## Stack (fixed — do not substitute)
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (typed), Alembic, pandas
- Jobs: Celery + Celery Beat, Redis as broker and cache
- DB: PostgreSQL 16
- Frontend: React + TypeScript (Vite), TanStack Query, TanStack Table, React Router,
  Recharts, Tailwind mapped to CSS variables from `frontend/src/styles/tokens.css`
- API types: generate TS types from FastAPI's OpenAPI spec (openapi-typescript); never hand-write DTO types
- LLM (explanations only): Anthropic SDK, model name from env `LLM_MODEL`; deterministic template fallback
- Local infra: docker-compose (postgres, redis)
- Later extensions only (do NOT build unless a phase asks): 3D twin (react-three-fiber), statsforecast models,
  scheme slabs, markdown rules, WhatsApp, supplier scorecard, shelf vision

## Repository layout
```
backend/app/
  api/routers/      FastAPI routers (thin: auth, validation, call service)
  services/         business workflows (approval, transfer, dashboard, store inventory, ingestion, ledger)
  agents/           6 agents + orchestrator (modules, implement BaseAgent.run(ctx))
  tools/            deterministic, pure functions (requirement, cost model, transfer engine, PO builder,
                    forecast, basket, lost sales) — 100% unit-tested, no DB access
  domain/models/    SQLAlchemy models   schemas/  Pydantic DTOs   repositories/  DB access
  core/             config, security (JWT, roles), cache, logging, errors
  workers/          Celery app, beat schedule, tasks
backend/alembic/  backend/tests/{unit,integration,scenarios}
frontend/src/{app,components,features,pages,api,hooks,styles}
data/synthetic/   synthetic data generator      infra/docker-compose.yml
```

## Non-negotiable business rules (details and formulas in docs/02-technical-spec.md)
1. Own requirement = ceil(demand × (lead time of the supplier serving THAT store + review period))
   + ceil(demand × safety days) + min display qty. Available = shelf + backroom + incoming − reserved.
   Surplus = available − own requirement. Only surplus > 0 is transferable.
2. If a product sells high in every store (no surplus anywhere) → raise a PO, never transfer.
3. Donor protection: a transfer never takes a donor below its own requirement.
4. Transfer vs PO compares INCREMENTAL costs only (transport + handling vs order/delivery share
   + holding and expiry cost of donor surplus). Never compare against the full purchase price.
5. Partial surplus → transfer the surplus AND a PO for the remainder; show both quantities separately.
6. Transfer workflow: destination accepts → donor approves release → system re-checks surplus →
   dispatch → receiving supervisor confirms qty → ledger update (discrepancy recorded).
7. Consolidated PO: line-level L1 by each store's supervisor for its own lines; l1_deadline;
   undecided lines escalate (default) or expire; approved lines split into a child PO;
   L2 threshold checked on the PO that continues.
8. Stock changes only through the inventory movement ledger. Never update quantities directly.
9. Lost revenue and lost profit are separate KPIs.
10. Store Supervisors see only their own store's data; in cross-store recommendations show only the
    other store's name and offered quantity.
11. The LLM only writes explanation text; all numbers come from deterministic tools and are
    validated against evidence. PoC never sends real supplier orders (SimulatedSupplierGateway).

## Coding conventions
- Type hints everywhere; `ruff` + `mypy --strict` on backend/app; ESLint + `tsc --noEmit` on frontend.
- Use the exact class/function names and signatures from docs/02-technical-spec.md and the diagrams.
- Money: `Decimal` in Python, NUMERIC(14,2) in SQL; quantities are int; dates in UTC, display in IST.
- Routers stay thin; business logic in services/tools. Tools are pure and side-effect free.
- Errors: 403 permission, 404 not found, 409 state conflict, 422 validation — via core/errors.py.
- Every agent step logs through AgentRunLogger (tool calls, evidence, LLM usage).
- Business parameters live in the BusinessRule table / RunParams, never hard-coded.
- Frontend: use design tokens only (no new hex values), components shared across roles,
  every table has loading/empty/error states, status badges always include a text label.

## Commands
- Infra: `docker compose -f infra/docker-compose.yml up -d`
- Backend: `cd backend && uv sync` · `uv run alembic upgrade head` · `uv run uvicorn app.main:app --reload`
- Tests: `cd backend && uv run pytest -q` · lint: `uv run ruff check . && uv run mypy app`
- Worker: `uv run celery -A app.workers.celery_app worker -B -l info`
- Synthetic data: `uv run python -m data.synthetic.generate --scenarios all`
- Frontend: `cd frontend && npm install && npm run dev` · types: `npm run gen:api` · checks: `npm run lint && npm run typecheck`

## How to work with me
- Start each phase in plan mode: read the listed docs, propose a plan and file list, wait for approval.
- Work in small steps; run tests and lint after each step; show me failing tests honestly.
- Write tests first for tools/ (the worked example: Store C need 40, Store A surplus 24,
  Store B none → transfer 24 + PO 16).
- Ask before: adding a dependency, changing the DB schema outside a migration, or changing any rule above.
- Commit at the end of each phase with a clear message.
