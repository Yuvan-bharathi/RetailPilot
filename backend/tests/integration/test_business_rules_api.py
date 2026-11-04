"""GET/PUT /admin/business-rules (spec §5, §9; D-48) on PostgreSQL, through the HTTP API."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, Engine, text
from sqlalchemy.orm import Session

from app.agents.base import RunParams
from app.core import db as core_db
from app.core.config import get_settings
from app.main import create_app
from app.services.business_rule_service import RULES, RuleSpec, coerce
from scripts.seed import seed

USERS = ["admin", "sup.a", "sup.b", "sup.c"]


@pytest.fixture
def api(
    migrated_url: URL, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Any]]:
    with engine.begin() as conn:
        before = dict(
            conn.execute(
                text("SELECT rule_key, value::text FROM business_rule WHERE scope_store_id IS NULL")
            ).all()
        )
    seed(engine, "demo")
    monkeypatch.setenv("DATABASE_URL", migrated_url.render_as_string(hide_password=False))
    monkeypatch.setenv("JWT_SECRET", "business-rule-tests-" + "x" * 32)
    caches = (get_settings, core_db.get_async_engine, core_db.get_async_session_factory)
    for c in caches:
        c.cache_clear()
    try:
        with TestClient(create_app()) as client:

            def login(user: str) -> dict[str, str]:
                r = client.post("/api/v1/auth/login", json={"username": user, "password": "demo"})
                return {"Authorization": f"Bearer {r.json()['access_token']}"}

            yield client, login
    finally:
        for c in caches:
            c.cache_clear()
        with engine.begin() as conn:
            for key, value in before.items():
                conn.execute(
                    text(
                        "UPDATE business_rule SET value = CAST(:v AS jsonb) WHERE rule_key = :k AND scope_store_id IS NULL"
                    ),
                    {"k": key, "v": value},
                )
            conn.execute(text("DELETE FROM app_user WHERE username = ANY(:u)"), {"u": USERS})
            conn.execute(text("DELETE FROM store WHERE code IN ('A', 'B', 'C')"))


def test_admin_lists_every_registered_rule_with_its_seeded_value(api: tuple[TestClient, Any]) -> None:
    client, login = api
    rules = {r["key"]: r for r in client.get("/api/v1/admin/business-rules", headers=login("admin")).json()}
    assert set(rules) == {spec.key for spec in RULES}
    assert rules["po_l2_threshold"]["value"] == "50000" and rules["po_l2_threshold"]["kind"] == "money"
    assert rules["holding_cost_rate_per_day"]["value"] == "0.0005"
    assert rules["basket.min_support"]["value"] == 0.005
    assert rules["deadline_action"]["choices"] == ["ESCALATE", "EXPIRE"]


def test_supervisors_cannot_read_or_change_rules(api: tuple[TestClient, Any]) -> None:
    client, login = api
    sup = login("sup.a")
    assert client.get("/api/v1/admin/business-rules", headers=sup).status_code == 403
    assert (
        client.put("/api/v1/admin/business-rules/stale_days", json={"value": 5}, headers=sup).status_code
        == 403
    )


def test_update_is_validated_stored_and_read_by_the_next_run(
    api: tuple[TestClient, Any], engine: Engine
) -> None:
    client, login = api
    admin = login("admin")
    r = client.put("/api/v1/admin/business-rules/stale_days", json={"value": 5}, headers=admin)
    assert r.status_code == 200 and r.json()["value"] == 5
    r = client.put("/api/v1/admin/business-rules/order_fixed_cost", json={"value": "300"}, headers=admin)
    assert r.json()["value"] == "300.00"
    r = client.put("/api/v1/admin/business-rules/basket.min_support", json={"value": 0.004}, headers=admin)
    assert r.json()["value"] == 0.004
    with Session(engine) as s:
        params = RunParams.load(s)
    assert (params.stale_days, params.order_fixed_cost, params.basket["min_support"]) == (
        5,
        Decimal("300.00"),
        0.004,
    )
    assert params.basket["min_confidence"] == 0.2  # sibling keys of the object are kept


@pytest.mark.parametrize(
    ("key", "value", "status"),
    [
        ("stale_days", 0, 422),  # below minimum
        ("stale_days", 2.5, 422),  # not whole
        ("expiry_risk_pct", "1.5", 422),  # share above 1
        ("deadline_action", "IGNORE", 422),
        ("basket.exclude_promo_days", "yes", 422),
        ("no_such_rule", 1, 404),
    ],
)
def test_invalid_updates_are_refused(api: tuple[TestClient, Any], key: str, value: Any, status: int) -> None:
    client, login = api
    r = client.put(f"/api/v1/admin/business-rules/{key}", json={"value": value}, headers=login("admin"))
    assert r.status_code == status
    if status == 422:
        assert r.json()["error"]["details"][0]["field"] == key


def test_coerce_normalises_stored_forms() -> None:
    money = RuleSpec("m", "g", "l", "d", "money", 0)
    assert coerce(money, 250) == "250.00"
    rate = RuleSpec("r", "g", "l", "d", "decimal", 0, 1)
    assert coerce(rate, "0.00050") == "0.0005"
    with pytest.raises(Exception, match="Invalid"):
        coerce(money, True)
