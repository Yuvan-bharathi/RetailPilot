"""Empty the business data for a fresh demo (Phase 9). Keeps the schema, migrations and BusinessRule rows.

    cd backend && uv run python -m scripts.reset_demo [--yes]

Refuses to run outside APP_ENV=local unless --yes is given. Also clears the dashboard/inbox cache keys in Redis.
"""

from __future__ import annotations

import argparse
import json

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sync_engine
from app.domain.models import MATERIALIZED_VIEWS, Base

KEEP = {"business_rule"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="confirm outside APP_ENV=local")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.app_env != "local" and not args.yes:
        raise SystemExit(f"APP_ENV={settings.app_env}: pass --yes to empty this database.")

    tables = sorted(t for t in Base.metadata.tables if t not in KEEP)
    with Session(get_sync_engine()) as session, session.begin():
        # business_rule references store (per-store overrides), so TRUNCATE store … CASCADE would empty it too:
        # keep the global rules and drop only the store overrides, whose stores disappear.
        rules = session.execute(
            text("SELECT rule_key, value FROM business_rule WHERE scope_store_id IS NULL")
        ).all()
        session.execute(text(f"TRUNCATE {', '.join(tables)}, business_rule RESTART IDENTITY CASCADE"))
        for key, value in rules:
            session.execute(
                text("INSERT INTO business_rule (rule_key, value) VALUES (:k, CAST(:v AS jsonb))"),
                {"k": key, "v": json.dumps(value)},
            )
        for view in MATERIALIZED_VIEWS:
            session.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
    print(f"Emptied {len(tables)} tables; kept {len(rules)} global business rules.")

    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        removed = 0
        for prefix in ("dash:", "dashi:", "inbox:", "inv:", "latest_run_id"):
            keys = list(client.scan_iter(f"{prefix}*"))
            if keys:
                removed += int(client.delete(*keys))
        print(f"Cleared {removed} cache keys.")
    except redis.RedisError as exc:
        print(f"Redis not reachable ({type(exc).__name__}); cache keys expire on their own.")


if __name__ == "__main__":
    main()
