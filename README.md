# RetailPilot AI

AI replenishment platform for multi-store FMCG supermarkets: forecasts store-SKU demand, restocks related
products together, moves genuine surplus between own stores before buying, and prepares purchase orders for
human approval. Every agent decision is explained and logged.

- Requirements, spec, design system, scenarios, decisions: [`docs/`](docs/)
- Working rules for Claude Code: [`CLAUDE.md`](CLAUDE.md) · build order: [`PROMPTS.md`](PROMPTS.md)

## Prerequisites
Docker Desktop, [uv](https://docs.astral.sh/uv/) (installs Python 3.12 from `.python-version`), Node.js 20+, git.

## First run
```bash
cp .env.example .env                                         # local settings (git-ignored)
docker compose --env-file .env -f infra/docker-compose.yml up -d   # PostgreSQL 16 + Redis 7

cd backend
uv sync                                                      # Python 3.12 venv + dependencies
uv run uvicorn app.main:app --reload                         # http://localhost:8000/health · /docs

cd ../frontend
npm install
npm run dev                                                  # http://localhost:5173 (proxies /api to :8000)
```

## Everyday commands
| Task | Command |
|---|---|
| Backend tests | `cd backend && uv run pytest -q` |
| Backend lint + types | `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` |
| Migrations (Phase 2+) | `cd backend && uv run alembic upgrade head` |
| Celery worker + beat | `cd backend && uv run celery -A app.workers.celery_app worker -B -l info` |
| Export OpenAPI spec | `cd backend && uv run python -m scripts.export_openapi ../frontend/openapi.json` |
| Generate API types | `cd frontend && npm run gen:api` |
| Frontend checks | `cd frontend && npm run check && npm run build` (lint, typecheck, no-hex, API types, tests + axe) |
| Design system demo | `cd frontend && npm run dev` → sign in (admin / sup.a / sup.b / sup.c, password `demo`) → `/components` |
| Synthetic data (Phase 4+) | `uv run --project backend python -m data.synthetic.generate --scenarios all` (repo root) |
| Pre-commit hooks | `uvx pre-commit install` |

## Layout
```
backend/app/{api/routers, services, agents, tools, domain/{models,schemas,repositories}, core, workers}
backend/{alembic, tests/{unit,integration,scenarios}, scripts}
frontend/src/{app, components, features, pages, api, hooks, styles}
data/synthetic/   infra/docker-compose.yml   docs/
```
