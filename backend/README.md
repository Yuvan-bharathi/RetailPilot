# RetailPilot AI — backend

FastAPI API, agents, deterministic tools and Celery jobs. See the repository `README.md` and `CLAUDE.md`.

```
uv sync                                   # create .venv with Python 3.12 and install deps
uv run uvicorn app.main:app --reload      # API on http://localhost:8000  (GET /health)
uv run pytest -q                          # tests
uv run ruff check . && uv run mypy        # lint + strict typing (app/)
uv run celery -A app.workers.celery_app worker -B -l info
uv run python -m scripts.export_openapi ../frontend/openapi.json
```
