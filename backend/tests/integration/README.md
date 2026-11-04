Integration tests need PostgreSQL from `infra/docker-compose.yml`
(`docker compose --env-file .env -f infra/docker-compose.yml up -d`, from the repo root).

- `conftest.py` creates a fresh `retailpilot_test` database next to DATABASE_URL's database, runs
  `alembic upgrade head` on it once per session and drops it afterwards; `test_migrations.py` uses its own
  `retailpilot_test_migrations` database for the upgrade/downgrade round trip.
- The `db` fixture is a connection inside a transaction that is always rolled back.
- `count_queries(engine)` records the SQL an engine (sync or async) sends, savepoints excluded — Phase 6 uses it
  to assert that list endpoints run the same number of queries for 1 row and for N rows (D-39).
- Every test here is marked `integration` automatically and skipped with the reason when PostgreSQL is not
  reachable.
