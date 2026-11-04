"""Seed the PoC stores and users (D-35). Idempotent: existing rows are left untouched.

    cd backend && uv run python -m scripts.seed

- Stores A, B, C use the synthetic generator's fixed ids (UUIDv5 of the store code), so the Phase 4b data load
  refers to the same rows.
- Users: `admin` (Super Admin) and `sup.a` / `sup.b` / `sup.c` (one Store Supervisor per store) — the same names as
  the frontend mock. The password comes from SEED_USER_PASSWORD; the demo password `demo` is used only when
  APP_ENV=local. Passwords are stored as bcrypt hashes and never appear in migrations.
- BusinessRule defaults are not seeded here: migration 0002 does that.
"""

import argparse
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_sync_engine
from app.core.security import hash_password
from app.domain.models import AppUser, Store
from app.domain.models.enums import Role
from data.synthetic.catalog import REGION, STORES

DEMO_PASSWORD = "demo"


@dataclass(frozen=True)
class SeedResult:
    stores_created: int
    users_created: int


def seed_password(settings: Settings) -> str:
    if settings.seed_user_password is not None:
        return settings.seed_user_password.get_secret_value()
    if settings.app_env == "local":
        return DEMO_PASSWORD
    raise SystemExit("SEED_USER_PASSWORD must be set outside APP_ENV=local")


def seed(engine: Engine, password: str) -> SeedResult:
    hashed = hash_password(password)
    store_rows = [
        {
            "store_id": s.store_id,
            "code": s.code,
            "name": s.name,
            "region": REGION,
            "store_type": s.store_type,
            "display_capacity": s.display_capacity,
        }
        for s in STORES
    ]
    user_rows = [
        {"username": "admin", "name": "Super Admin", "role": Role.SUPER_ADMIN.value, "store_id": None},
        *(
            {
                "username": f"sup.{s.code.lower()}",
                "name": f"Supervisor, {s.name}",
                "role": Role.STORE_SUPERVISOR.value,
                "store_id": s.store_id,
            }
            for s in STORES
        ),
    ]
    for row in user_rows:
        row["password_hash"] = hashed
    with Session(engine) as session, session.begin():
        # RETURNING lists only the rows actually inserted (rowcount is -1 for this multi-row form)
        stores = session.scalars(
            insert(Store)
            .values(store_rows)
            .on_conflict_do_nothing(index_elements=["store_id"])
            .returning(Store.store_id)
        ).all()
        users = session.scalars(
            insert(AppUser)
            .values(user_rows)
            .on_conflict_do_nothing(index_elements=["username"])
            .returning(AppUser.user_id)
        ).all()
    return SeedResult(stores_created=len(stores), users_created=len(users))


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    result = seed(get_sync_engine(), seed_password(get_settings()))
    print(f"Seed done: {result.stores_created} store(s) and {result.users_created} user(s) created")


if __name__ == "__main__":
    main()
