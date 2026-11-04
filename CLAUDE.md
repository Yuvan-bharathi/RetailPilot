# RetailPilot AI — project instructions for Claude Code

AI replenishment platform for multi-store FMCG supermarkets: forecasts store-SKU demand,
restocks related products together, moves genuine surplus between own stores before buying,
and prepares purchase orders for human approval. Every agent decision is explained and logged.

## Source of truth (read the relevant file before working on an area)
- Business requirements (frozen v2.2): `docs/01-business-requirements-v2.2.md`
- Technical spec — formulas, functions, states, API, permissions: `docs/02-technical-spec.md`
- Design system (frozen v1.0) + UI rules: `docs/03-design-system.md`
- Demo scenarios and acceptance tests: `docs/04-demo-scenarios.md`
- Class and sequence diagrams (PlantUML, code level): `docs/diagrams/` (cd1–cd4, sd01–sd16)
- Decision log (Phase 0 review decisions D-01…, binding): `docs/05-decision-log.md`
- Build order and phase prompts: `PROMPTS.md`
If code and docs disagree, follow the docs and tell me. Never silently change a business rule.

## Stack (fixed — do not substitute)
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (typed), Alembic, pandas
- Jobs: Celery + Celery Beat, Redis as broker and cache
- DB: PostgreSQL 16
- Frontend: React + TypeScript (Vite), TanStack Query, TanStack Table, React Router,
  Recharts, Tailwind v4 with tokens mapped via `@theme` to CSS variables from `frontend/src/styles/tokens.css`
- API types: generate TS types from FastAPI's OpenAPI spec (openapi-typescript); never hand-write DTO types
- LLM (explanations only, D-44): Groq chat completions (httpx) with OpenAI open-weight models —
  `LLM_MODEL` default `openai/gpt-oss-120b`, `LLM_FALLBACK_MODEL` `openai/gpt-oss-20b`; key `GROQ_API_KEY`;
  strict JSON-schema output; every number checked against the evidence; deterministic template fallback
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
  domain/
    models/         SQLAlchemy models
    schemas/        Pydantic DTOs (request/response)
    repositories/   DB access
  core/             config, security (JWT via pyjwt, bcrypt passwords, roles), cache, logging, errors
  workers/          Celery app, beat schedule, tasks
backend/alembic/  backend/tests/{unit,integration,scenarios}
frontend/src/{app,components,features,pages,api,hooks,styles}
data/synthetic/   synthetic data generator (repo root; run with the backend environment)
infra/docker-compose.yml
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
   dispatch → receiving supervisor confirms qty → ledger update (discrepancy recorded on the transfer).
   On acceptance: receiver incoming += qty, donor reserved += qty; released on reject/cancel.
   A cancelled transfer is NOT carried forward — the next nightly run recalculates the need.
   Each nightly run marks the previous run's untouched recommendations, PROPOSED transfers and
   undecided PENDING_L1 POs as SUPERSEDED.
7. Consolidated PO: line-level L1 by each store's supervisor for its own PENDING lines before l1_deadline;
   undecided lines escalate (default) or expire; the Super Admin decides ESCALATED lines (recorded as L1
   for that store); L1 finalises only when no line is PENDING or ESCALATED; approved lines split into a
   child PO; L2 threshold checked on the PO that continues. Approved/submitted lines count as incoming
   until goods receipt.
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
- Backend: `cd backend && uv sync` · `uv run alembic upgrade head` · `uv run python -m scripts.seed` ·
  `uv run uvicorn app.main:app --reload --loop app.core.db:selector_event_loop` (selector loop: psycopg async
  cannot use Windows' default Proactor loop, D-36)
- Tests: `cd backend && uv run pytest -q` (integration tests need `docker compose … up -d`; they create and drop
  the `retailpilot_test` database and are skipped with a reason when PostgreSQL is down) · lint: `uv run ruff check --config pyproject.toml . ../data && uv run mypy`
  (always pass `--config pyproject.toml` when ruff also checks `../data`: data/ has no config of its own, so
  without it ruff falls back to its defaults; mypy already covers app/ and ../data via pyproject.toml)
- Worker: `uv run celery -A app.workers.celery_app worker -B -l info`
- Synthetic data (from the repo root): `uv run --project backend python -m data.synthetic.generate --scenarios all`
- Frontend: `cd frontend && npm install && npm run dev` (mock API: `VITE_USE_MOCKS=true` in `.env.development`;
  demo users admin / sup.a / sup.b / sup.c, password `demo`) · all checks: `npm run check`
  (lint, typecheck, check:no-hex, check:api, vitest incl. axe) · build: `npm run build` ·
  `npm run format:check` (Prettier 3.9.10 pinned, `.prettierrc.json` printWidth 120; not yet part of `check` —
  existing files are reformatted in a separate commit when approved)
- Mock data (frontend): `cd backend && uv run python -m scripts.export_mock_fixtures` regenerates
  `frontend/src/mocks/data/fixtures.json` from the synthetic data with the real tools (a test fails if it is stale)
- API contract: after changing a DTO/route run `cd backend && uv run python -m scripts.export_openapi ../frontend/openapi.json`
  then `cd ../frontend && npm run gen:api` — both sides are checked (test_contract.py, check:api)

## How to work with me
- Start each phase in plan mode: read the listed docs, propose a plan and file list, wait for approval.
- Work in small steps; run tests and lint after each step; show me failing tests honestly.
- Write tests first for tools/ (the worked example: Store C need 40, Store A surplus 24,
  Store B none → transfer 24 + PO 16).
- Ask before: adding a dependency, changing the DB schema outside a migration, or changing any rule above.
- Never run a tool through `npx` / `uvx` (or `npm exec`, `pipx run`) unless it is declared in
  `frontend/package.json` / `backend/pyproject.toml`; use `npx --no-install …` or the npm/uv script so an
  undeclared tool can never be downloaded and run. Formatting uses the pinned project tools only
  (`ruff format`; Prettier via `npm run format:check`).
- Commit at the end of each phase with a clear message.
