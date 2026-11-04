"""The five demo scenarios (docs/04-demo-scenarios.md) through the REAL pipeline (Phase 5 acceptance, D-47).

The small synthetic dataset is bulk-loaded into its own database (synthetic loader, COPY), then the nightly
orchestrator runs for the dataset's run date with templates instead of the LLM. Every expected number comes from
the generator's manifest (the planted values), never from this test.
"""

import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from alembic import command
from app.agents.orchestrator import WorkflowOrchestrator
from app.core.config import get_settings
from app.domain.models import Recommendation, ReplenishmentNeed, TransferOrder
from app.services.pos_source import SyntheticPosSource
from app.services.synthetic_loader import load_synthetic
from data.synthetic.config import GeneratorConfig
from data.synthetic.generate import generate
from data.synthetic.reader import Dataset, load_dataset
from tests.integration.conftest import alembic_config, drop_database, recreate_database

pytestmark = pytest.mark.scenario
DB = "retailpilot_test_scenarios"


class NoCache:
    def get(self, key: str) -> None:
        return None

    def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def __getattr__(self, name: str) -> Any:  # warm / invalidate / set_latest_run_id: no-ops
        return lambda *a, **k: 0


@pytest.fixture(scope="module")
def run(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LLM_PROVIDER", "template")  # deterministic text, no network
        get_settings.cache_clear()
        url = recreate_database(admin_engine, DB)
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url, poolclass=NullPool)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = generate(GeneratorConfig(profile="small"), Path(tmp))
            ds = load_dataset(Path(tmp))
        with Session(engine) as session:
            report = load_synthetic(session, ds)
            session.commit()
        run_date = date.fromisoformat(manifest["run_date"])
        with Session(engine) as session:
            summary = WorkflowOrchestrator(
                session,
                pos_source=SyntheticPosSource(ds),
                cache_service=NoCache(),  # type: ignore[arg-type]
            ).run_nightly(run_date=run_date)
            session.commit()
        yield {"engine": engine, "ds": ds, "manifest": manifest, "summary": summary, "load": report}
        engine.dispose()
        drop_database(admin_engine, DB)
    get_settings.cache_clear()


def _store(run: dict[str, Any], code: str) -> UUID:
    return UUID(run["manifest"]["stores"][code])


def _recs(run: dict[str, Any], product: str, rec_type: str) -> dict[UUID, int]:
    with Session(run["engine"]) as s:
        rows = s.execute(
            select(Recommendation.store_id, Recommendation.qty).where(
                Recommendation.run_id == run["summary"].run_id,
                Recommendation.product_id == UUID(product),
                Recommendation.rec_type == rec_type,
            )
        ).all()
    return {store: qty for store, qty in rows}


def _transfers(run: dict[str, Any], product: str) -> list[tuple[UUID, UUID, int, bool]]:
    with Session(run["engine"]) as s:
        rows = s.execute(
            select(
                TransferOrder.from_store_id,
                TransferOrder.to_store_id,
                TransferOrder.qty,
                TransferOrder.is_expiry_aware,
            )
            .join(Recommendation, Recommendation.rec_id == TransferOrder.source_rec_id)
            .where(Recommendation.run_id == run["summary"].run_id, TransferOrder.product_id == UUID(product))
        ).all()
    return [tuple(r) for r in rows]  # type: ignore[misc]


def test_pipeline_loads_the_dataset_and_succeeds(run: dict[str, Any]) -> None:
    assert run["load"].reconciliation_adjustments >= 1  # the planted stock mismatch is reconciled
    assert run["summary"].status == "SUCCESS", run["summary"].error
    with Session(run["engine"]) as s:
        mismatch = run["manifest"]["edge_cases"]["stock_mismatch"]
        adj = s.execute(
            text(
                "SELECT qty FROM inventory_movement WHERE movement_type = 'ADJUSTMENT' AND reference_type = 'RECON' "
                "AND store_id = :s AND product_id = :p AND business_date = :d"
            ),
            {"s": mismatch["store_id"], "p": mismatch["product_id"], "d": mismatch["date"]},
        ).scalar()
    assert adj == mismatch["delta"]


def test_ledger_sums_to_the_stock_position(run: dict[str, Any]) -> None:
    """Rule 8: the position equals the sum of the movements for every store-SKU."""
    with Session(run["engine"]) as s:
        broken = s.execute(
            text(
                "SELECT count(*) FROM inventory_position ip LEFT JOIN ("
                " SELECT store_id, product_id, SUM(qty) AS q FROM inventory_movement GROUP BY store_id, product_id"
                ") m USING (store_id, product_id) WHERE ip.shelf_qty + ip.backroom_qty <> COALESCE(m.q, 0)"
            )
        ).scalar()
    assert broken == 0


def test_scenario_1_sells_high_everywhere_purchase_orders_only(run: dict[str, Any]) -> None:
    sc = run["manifest"]["scenarios"]["1"]
    expected = {_store(run, code): qty for code, qty in sc["expected"]["po_needs"].items()}
    assert _recs(run, sc["product_id"], "REORDER") == expected
    assert _transfers(run, sc["product_id"]) == []
    with Session(run["engine"]) as s:
        reasons = set(
            s.scalars(
                select(ReplenishmentNeed.reason).where(
                    ReplenishmentNeed.run_id == run["summary"].run_id,
                    ReplenishmentNeed.product_id == UUID(sc["product_id"]),
                )
            )
        )
    assert reasons == {"NO_SURPLUS_IN_ANY_STORE"}


def test_scenario_2_full_transfer_no_purchase_order(run: dict[str, Any]) -> None:
    sc = run["manifest"]["scenarios"]["2"]
    assert _transfers(run, sc["product_id"]) == [
        (_store(run, "A"), _store(run, "C"), sc["expected"]["transfer_qty"], False)
    ]
    assert _store(run, "C") not in _recs(run, sc["product_id"], "REORDER")


def test_scenario_3_partial_surplus_transfer_plus_purchase_order(run: dict[str, Any]) -> None:
    sc = run["manifest"]["scenarios"]["3"]
    assert _transfers(run, sc["product_id"]) == [
        (_store(run, "A"), _store(run, "C"), sc["expected"]["transfer_qty"], False)
    ]
    assert _recs(run, sc["product_id"], "REORDER") == {_store(run, "C"): sc["expected"]["po_qty"]}


def test_scenario_4_reorder_with_co_replenished_complement(run: dict[str, Any]) -> None:
    sc = run["manifest"]["scenarios"]["4"]
    store = _store(run, sc["store"])
    assert _recs(run, sc["bread_id"], "REORDER") == {store: sc["expected"]["bread_po_qty"]}
    assert _recs(run, sc["butter_id"], "CO_REPLENISH") == {store: sc["expected"]["butter_co_replenish_qty"]}


def test_scenario_5_expiry_aware_transfer_of_the_at_risk_units(run: dict[str, Any]) -> None:
    sc = run["manifest"]["scenarios"]["5"]
    assert _transfers(run, sc["product_id"]) == [
        (_store(run, sc["from"]), _store(run, sc["to"]), sc["expected"]["at_risk"], True)
    ]


def test_stale_sku_is_low_confidence(run: dict[str, Any]) -> None:
    stale = run["manifest"]["edge_cases"]["stale_sku"]
    with Session(run["engine"]) as s:
        confidence = s.execute(
            text("SELECT confidence FROM forecast WHERE run_id = :r AND store_id = :s AND product_id = :p"),
            {"r": run["summary"].run_id, "s": stale["store_id"], "p": stale["product_id"]},
        ).scalar()
    assert confidence == "LOW"


def test_every_recommendation_has_an_explanation(run: dict[str, Any]) -> None:
    with Session(run["engine"]) as s:
        missing = s.execute(
            text(
                "SELECT count(*) FROM recommendation WHERE run_id = :r AND (explanation IS NULL OR explanation = '')"
            ),
            {"r": run["summary"].run_id},
        ).scalar()
    assert missing == 0


def _unused(_: Dataset) -> None:  # keep the import used for typing readers
    return None


def test_every_recommendation_carries_d34_evidence(run: dict[str, Any]) -> None:
    """D-34: evidence is the discriminated union, on the recommendation and in decision_evidence."""
    from pydantic import TypeAdapter

    from app.domain.schemas.dtos import Evidence

    adapter = TypeAdapter(Evidence)
    with Session(run["engine"]) as s:
        rows = s.execute(
            text(
                "SELECT r.rec_type, r.status, r.evidence, d.data FROM recommendation r "
                "LEFT JOIN decision_evidence d ON d.rec_id = r.rec_id WHERE r.run_id = :r"
            ),
            {"r": run["summary"].run_id},
        ).all()
    assert rows
    bad = []
    for rec_type, status, evidence, logged in rows:
        try:
            adapter.validate_python(evidence)
            assert logged == evidence
        except Exception as exc:  # collect all, report together
            bad.append((rec_type, status, str(exc)[:120]))
    assert bad == []


# --- through the HTTP API, as each demo user (D-32 per-viewer scoping) -----------------------------------------------


@pytest.fixture(scope="module")
def api(run: dict[str, Any]) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from app.core import db as core_db
    from app.main import create_app
    from scripts.seed import seed

    seed(run["engine"], "demo")
    caches = (get_settings, core_db.get_async_engine, core_db.get_async_session_factory)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", run["engine"].url.render_as_string(hide_password=False))
        mp.setenv("LLM_PROVIDER", "template")
        mp.setenv("JWT_SECRET", "scenario-tests-" + "x" * 32)
        for c in caches:
            c.cache_clear()
        with TestClient(create_app()) as client:

            def as_user(username: str) -> dict[str, str]:
                r = client.post("/api/v1/auth/login", json={"username": username, "password": "demo"})
                assert r.status_code == 200, r.text
                return {"Authorization": f"Bearer {r.json()['access_token']}"}

            yield client, as_user
    for c in caches:
        c.cache_clear()


def _transfer_rec_id(run: dict[str, Any], scenario: str) -> str:
    product = run["manifest"]["scenarios"][scenario]["product_id"]
    with Session(run["engine"]) as s:
        return str(
            s.execute(
                text(
                    "SELECT r.rec_id FROM recommendation r JOIN transfer_order t ON t.source_rec_id = r.rec_id "
                    "WHERE r.run_id = :run AND r.product_id = :p"
                ),
                {"run": run["summary"].run_id, "p": product},
            ).scalar_one()
        )


def test_api_destination_sees_donor_as_name_and_quantity_only(run: dict[str, Any], api: Any) -> None:
    client, as_user = api
    body = client.get(
        f"/api/v1/recommendations/{_transfer_rec_id(run, '3')}", headers=as_user("sup.c")
    ).json()
    ev = body["evidence"]
    assert ev["kind"] == "TRANSFER" and ev["transfer_qty"] == 24 and ev["po_remainder_qty"] == 16
    assert ev["donor"]["store"]["name"].startswith("Store A")
    assert ev["donor_surplus"] is None and ev["donor_protected_requirement"] is None
    assert body["recommendation"]["explanation"]


def test_api_donor_sees_its_own_surplus_and_others_are_refused(run: dict[str, Any], api: Any) -> None:
    client, as_user = api
    rec = _transfer_rec_id(run, "3")
    donor = client.get(f"/api/v1/recommendations/{rec}", headers=as_user("sup.a"))
    assert donor.status_code == 200
    assert donor.json()["evidence"]["donor_surplus"] == 24
    assert client.get(f"/api/v1/recommendations/{rec}", headers=as_user("sup.b")).status_code == 403


def test_api_dashboard_and_inventory_answer_for_each_role(run: dict[str, Any], api: Any) -> None:
    client, as_user = api
    admin, sup = as_user("admin"), as_user("sup.c")
    for path in ("/api/v1/dashboard", "/api/v1/dashboard/insights"):
        assert client.get(path, headers=admin).status_code == 200
    summary = client.get("/api/v1/dashboard", headers=sup).json()
    assert summary["store"]["name"].startswith("Store C")
    assert float(summary["inventory_value"]) > 0
    inventory = client.get(f"/api/v1/stores/{_store(run, 'C')}/inventory?page_size=5", headers=sup)
    assert inventory.status_code == 200 and inventory.json()["total"] > 0
    assert client.get(f"/api/v1/stores/{_store(run, 'A')}/inventory", headers=sup).status_code == 403
