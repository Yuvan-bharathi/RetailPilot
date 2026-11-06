"""Agent console and Objective III agents on PostgreSQL (docs/09 §7, docs/08 §5, D-50).

One database for the module (small synthetic profile + a real nightly run); the tests run in file order and build
on each other (toggles → next run → triggers → decisions)."""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, insert, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from alembic import command
from app.agents.base import AgentResult, BaseAgent, RunContext
from app.agents.llm.chat import RoutedChatLLM, ScriptedChatLLM
from app.agents.orchestrator import WorkflowOrchestrator
from app.core.config import get_settings
from app.domain.models import AgentDecision, AgentPreviewOutput, AgentRun, Recommendation
from app.services.pos_source import SyntheticPosSource
from app.services.synthetic_loader import load_synthetic
from data.synthetic.config import GeneratorConfig
from data.synthetic.generate import generate
from data.synthetic.reader import load_dataset
from tests.integration.conftest import alembic_config, drop_database, recreate_database
from tests.scenarios.test_demo_scenarios import NoCache

pytestmark = pytest.mark.scenario
DB = "retailpilot_test_agents"


@pytest.fixture(scope="module")
def env(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    from fastapi.testclient import TestClient

    from app.core import db as core_db
    from app.main import create_app
    from scripts.seed import seed
    from scripts.seed_agents import load_policies

    caches = (
        get_settings,
        core_db.get_async_engine,
        core_db.get_async_session_factory,
        core_db.get_sync_engine,
        core_db.get_sync_session_factory,
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LLM_PROVIDER", "template")
        get_settings.cache_clear()  # never a live model in tests (the repo .env may select Groq)
        url = recreate_database(admin_engine, DB)
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url, poolclass=NullPool)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = generate(GeneratorConfig(profile="small"), Path(tmp))
            ds = load_dataset(Path(tmp))
        with Session(engine) as s:
            load_synthetic(s, ds)
            s.commit()
        seed(engine, "demo")
        run_date = date.fromisoformat(manifest["run_date"])
        with Session(engine) as s:
            summary = WorkflowOrchestrator(
                s, pos_source=SyntheticPosSource(ds), cache_service=NoCache()
            ).run_nightly(  # type: ignore[arg-type]
                run_date=run_date
            )
            load_policies(s)
            s.commit()
        mp.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        mp.setenv("JWT_SECRET", "agent-console-tests-" + "x" * 32)
        mp.setattr("app.services.cache_service.CacheService", NoCache)
        for c in caches:
            c.cache_clear()
        with TestClient(create_app()) as client:

            def as_user(username: str) -> dict[str, str]:
                r = client.post("/api/v1/auth/login", json={"username": username, "password": "demo"})
                assert r.status_code == 200, r.text
                return {"Authorization": f"Bearer {r.json()['access_token']}"}

            yield {
                "engine": engine,
                "ds": ds,
                "manifest": manifest,
                "summary": summary,
                "run_date": run_date,
                "client": client,
                "as": as_user,
            }
        for c in caches:
            c.cache_clear()
        engine.dispose()
        drop_database(admin_engine, DB)


def _scalar(env: dict[str, Any], q: Any) -> Any:
    with Session(env["engine"]) as s:
        return s.scalar(q)


def _pending(env: dict[str, Any]) -> int:
    return int(
        _scalar(
            env, select(func.count()).select_from(Recommendation).where(Recommendation.status == "PENDING")
        )
    )


def _orch(env: dict[str, Any], s: Session, **kw: Any) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(s, pos_source=SyntheticPosSource(env["ds"]), cache_service=NoCache(), **kw)  # type: ignore[arg-type]


# --- access and registry ---------------------------------------------------------------------------------------


def test_registry_lists_every_agent_and_is_admin_only(env: dict[str, Any]) -> None:
    c, as_user = env["client"], env["as"]
    body = c.get("/api/v1/agents", headers=as_user("admin")).json()
    assert {a["agent_key"] for a in body["items"]} == {
        "sales_analytics",
        "demand_forecasting",
        "related_product",
        "stock_balancing",
        "freshness",
        "purchase_order",
        "ask_retailpilot",
        "data_quality",
        "replenishment_action",
        "run_coordinator",
        "recommendation_reviewer",
    }
    assert body["llm_enabled"] is True and body["paused_banner"] is None
    for path in ["/agents", "/agents/stock_balancing", "/agent-runs", "/agent-decisions", "/pipeline/runs"]:
        assert c.get(f"/api/v1{path}", headers=as_user("sup.a")).status_code == 403
    detail = c.get("/api/v1/agents/ask_retailpilot", headers=as_user("admin")).json()
    assert detail["prompt_text"].startswith("# Ask RetailPilot")
    assert "approve" not in " ".join(detail["read_tools"] + detail["draft_tools"])


def test_every_nightly_output_has_a_decision(env: dict[str, Any]) -> None:
    run_id = env["summary"].run_id
    recs = _scalar(
        env, select(func.count()).select_from(Recommendation).where(Recommendation.run_id == run_id)
    )
    decided = _scalar(
        env, select(func.count(func.distinct(AgentDecision.rec_id))).where(AgentDecision.run_id == run_id)
    )
    assert recs > 0 and decided == recs
    pos = _scalar(env, text("SELECT count(*) FROM purchase_order WHERE run_id = :r").bindparams(r=run_id))
    po_dec = _scalar(
        env,
        select(func.count()).select_from(AgentDecision).where(AgentDecision.decision_type == "PO_DRAFTED"),
    )
    assert po_dec == pos


# --- toggles -----------------------------------------------------------------------------------------------------


def test_toggle_needs_reason_and_double_confirmation_and_is_audited(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    assert (
        c.patch("/api/v1/agents/freshness", json={"enabled": False, "reason": ""}, headers=h).status_code
        == 422
    )
    r = c.patch(
        "/api/v1/agents/stock_balancing", json={"enabled": False, "reason": "migration tonight"}, headers=h
    )
    assert r.status_code == 422 and "confirm_critical" in r.text
    assert (
        c.patch(
            "/api/v1/agents/freshness", json={"enabled": False, "reason": "x"}, headers=env["as"]("sup.a")
        ).status_code
        == 403
    )
    r = c.patch(
        "/api/v1/agents/freshness",
        json={"enabled": False, "reason": "Batch data being re-imported"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["agent"]["enabled"] is False
    top = body["toggle_history"][0]
    assert (top["agent_key"], top["enabled"], top["previous_enabled"], top["reason"]) == (
        "freshness",
        False,
        True,
        "Batch data being re-imported",
    )
    assert top["updated_by"]  # who
    assert (
        c.patch(
            "/api/v1/agents/freshness", json={"enabled": False, "reason": "again please"}, headers=h
        ).status_code
        == 409
    )


def test_toggle_applies_from_the_next_run_and_skips_the_stage(env: dict[str, Any]) -> None:
    with Session(env["engine"]) as s:
        summary = _orch(env, s).run_nightly(run_date=env["run_date"] + timedelta(days=1))
        s.commit()
        stages = dict(
            s.execute(
                select(AgentRun.agent_key, AgentRun.status).where(AgentRun.parent_run_id == summary.run_id)
            ).all()
        )
        root = s.get(AgentRun, summary.run_id)
        assert root is not None and root.config_snapshot is not None
        assert root.config_snapshot["freshness"] is False
    assert stages["freshness"] == "SKIPPED_DISABLED"
    assert stages["stock_balancing"] == "SUCCESS"
    assert (
        _scalar(
            env,
            select(func.count())
            .select_from(AgentDecision)
            .where(AgentDecision.run_id == summary.run_id, AgentDecision.agent_key == "freshness"),
        )
        == 0
    )
    env["run2"] = summary.run_id
    env["client"].patch(
        "/api/v1/agents/freshness",
        json={"enabled": True, "reason": "Batch data re-imported"},
        headers=env["as"]("admin"),
    )


def test_critical_agent_off_pauses_replenishment_and_keeps_results(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    r = c.patch(
        "/api/v1/agents/purchase_order",
        headers=h,
        json={"enabled": False, "reason": "Supplier master data migration", "confirm_critical": True},
    )
    assert r.status_code == 200
    banner = c.get("/api/v1/agents", headers=h).json()["paused_banner"]
    assert banner and "Supplier master data migration" in banner
    before = _pending(env)
    with Session(env["engine"]) as s:
        summary = _orch(env, s).run_nightly(run_date=env["run_date"] + timedelta(days=2))
        s.commit()
        stages = dict(
            s.execute(
                select(AgentRun.agent_key, AgentRun.status).where(AgentRun.parent_run_id == summary.run_id)
            ).all()
        )
    assert summary.status == "PAUSED"
    assert stages["purchase_order"] == "SKIPPED_DISABLED"
    assert stages["stock_balancing"] == "SKIPPED_DEPENDENCY"
    assert stages["sales_analytics"] == "SUCCESS"
    assert _pending(env) == before  # nothing superseded, nothing new
    c.patch(
        "/api/v1/agents/purchase_order", json={"enabled": True, "reason": "Migration finished"}, headers=h
    )


def test_global_llm_switch_skips_every_llm_agent(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    assert (
        c.patch(
            "/api/v1/agents/llm", json={"enabled": False, "reason": "Cost freeze this week"}, headers=h
        ).status_code
        == 200
    )
    with Session(env["engine"]) as s:
        summary = _orch(env, s).run_nightly(run_date=env["run_date"] + timedelta(days=3))
        s.commit()
        stages = dict(
            s.execute(
                select(AgentRun.agent_key, AgentRun.status).where(AgentRun.parent_run_id == summary.run_id)
            ).all()
        )
    assert stages["data_quality"] == stages["recommendation_reviewer"] == "SKIPPED_DISABLED"
    assert "run_coordinator" not in stages  # off → deterministic orchestrator handles failures
    assert stages["stock_balancing"] == "SUCCESS"
    assert c.get("/api/v1/assistant/status", headers=env["as"]("sup.a")).json()["enabled"] is False
    assert (
        c.post(
            "/api/v1/assistant/ask", json={"question": "why butter"}, headers=env["as"]("sup.a")
        ).status_code
        == 409
    )
    c.patch("/api/v1/agents/llm", json={"enabled": True, "reason": "Budget approved"}, headers=h)
    env["latest_run"] = summary.run_id


# --- manual triggers ------------------------------------------------------------------------------------------


def test_dry_run_never_changes_inbox_pos_or_transfers(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")

    def counts():
        return _scalar(
            env,
            text(
                "SELECT (SELECT count(*) FROM recommendation) * 1000000 + (SELECT count(*) FROM purchase_order) * 1000 "
                "+ (SELECT count(*) FROM transfer_order)"
            ),
        )

    before, pending = counts(), _pending(env)
    preview = c.get("/api/v1/agents/stock_balancing/trigger-preview?mode=DRY_RUN", headers=h).json()
    assert preview["allowed"] is True
    assert {u["agent_key"] for u in preview["upstream"]} >= {"demand_forecasting"}
    r = c.post("/api/v1/agents/stock_balancing/runs", json={"mode": "DRY_RUN"}, headers=h)
    assert r.status_code == 202
    run_id = r.json()["run_id"]  # TestClient runs the background task before returning
    trace = c.get(f"/api/v1/agent-runs/{run_id}", headers=h).json()
    assert trace["run"]["status"] == "SUCCESS", trace
    assert trace["run"]["trigger_type"] == "MANUAL_DRY_RUN"
    assert trace["previews"], "a dry run stores its outputs as previews"
    assert counts() == before and _pending(env) == pending
    assert (
        _scalar(
            env,
            select(func.count())
            .select_from(AgentDecision)
            .where(AgentDecision.run_id == UUID(run_id), AgentDecision.mode == "LIVE"),
        )
        == 0
    )
    assert (
        _scalar(
            env,
            select(func.count())
            .select_from(AgentPreviewOutput)
            .where(AgentPreviewOutput.run_id == UUID(run_id)),
        )
        > 0
    )


def test_live_run_needs_reason_and_confirmation(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    assert c.post("/api/v1/agents/stock_balancing/runs", json={"mode": "LIVE"}, headers=h).status_code == 422
    assert (
        c.post(
            "/api/v1/agents/stock_balancing/runs", json={"mode": "LIVE", "reason": "late file"}, headers=h
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/agents/stock_balancing/runs", json={"mode": "DRY_RUN"}, headers=env["as"]("sup.a")
        ).status_code
        == 403
    )


def test_live_run_supersedes_and_publishes(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    old = set(
        _scalar_list(
            env,
            select(Recommendation.rec_id).where(
                Recommendation.status == "PENDING", Recommendation.rec_type == "TRANSFER"
            ),
        )
    )
    r = c.post(
        "/api/v1/agents/stock_balancing/runs",
        headers=h,
        json={"mode": "LIVE", "reason": "Late supplier file re-imported", "confirm": True},
    )
    assert r.status_code == 202, r.text
    run_id = UUID(r.json()["run_id"])
    trace = c.get(f"/api/v1/agent-runs/{run_id}", headers=h).json()
    assert trace["run"]["status"] in ("SUCCESS", "PARTIAL"), trace
    assert trace["run"]["reason"] == "Late supplier file re-imported" and trace["run"]["triggered_by"]
    children = {ch["agent_key"] for ch in trace["children"]}
    assert {"stock_balancing", "purchase_order"} <= children  # downstream re-run in live mode
    sb_old = set(
        _scalar_list(
            env,
            select(AgentDecision.rec_id).where(
                AgentDecision.agent_key == "stock_balancing", AgentDecision.run_id != run_id
            ),
        )
    )
    still_pending = (
        old
        & sb_old
        & set(_scalar_list(env, select(Recommendation.rec_id).where(Recommendation.status == "PENDING")))
    )
    assert not still_pending  # earlier stock-balancing recommendations were superseded
    assert (
        _scalar(
            env,
            select(func.count())
            .select_from(AgentDecision)
            .where(AgentDecision.run_id == run_id, AgentDecision.mode == "LIVE"),
        )
        > 0
    )


def _scalar_list(env: dict[str, Any], q: Any) -> list[Any]:
    with Session(env["engine"]) as s:
        return list(s.scalars(q))


def test_trigger_blocked_when_disabled_running_or_rate_limited(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    c.patch("/api/v1/agents/freshness", json={"enabled": False, "reason": "Testing the block"}, headers=h)
    assert c.post("/api/v1/agents/freshness/runs", json={"mode": "DRY_RUN"}, headers=h).status_code == 409
    c.patch("/api/v1/agents/freshness", json={"enabled": True, "reason": "Testing done"}, headers=h)
    with Session(env["engine"]) as s:  # 3 live triggers in the last hour → limit
        for _ in range(3):
            s.execute(
                insert(AgentRun).values(
                    agent_name="manual:freshness",
                    agent_key="freshness",
                    status="SUCCESS",
                    trigger_type="MANUAL_LIVE",
                    mode="LIVE",
                )
            )
        s.commit()
    p = c.get("/api/v1/agents/freshness/trigger-preview?mode=LIVE", headers=h).json()
    assert p["allowed"] is False and "Rate limit" in p["blocked_reason"]
    r = c.post(
        "/api/v1/agents/freshness/runs",
        json={"mode": "LIVE", "reason": "please run it", "confirm": True},
        headers=h,
    )
    assert r.status_code == 409
    assert (
        c.post("/api/v1/agents/freshness/runs", json={"mode": "DRY_RUN"}, headers=h).status_code == 202
    )  # dry runs are not limited
    running = uuid4()
    with Session(env["engine"]) as s:
        s.execute(
            insert(AgentRun).values(
                run_id=running,
                agent_name="nightly",
                status="RUNNING",
                run_date=env["run_date"] + timedelta(days=30),
            )
        )
        s.commit()
    assert (
        c.post("/api/v1/agents/sales_analytics/runs", json={"mode": "DRY_RUN"}, headers=h).status_code == 409
    )
    # cancel: the running run stops after its current step
    r = c.post(f"/api/v1/agent-runs/{running}/cancel", headers=h)
    assert r.status_code == 200 and _scalar(
        env, select(AgentRun.cancel_requested).where(AgentRun.run_id == running)
    )
    with Session(env["engine"]) as s:
        s.execute(text("UPDATE agent_run SET status = 'CANCELLED' WHERE run_id = :r"), {"r": running})
        s.commit()
    assert c.post(f"/api/v1/agent-runs/{running}/cancel", headers=h).status_code == 409


def test_cancelled_manual_run_stops_before_the_next_stage(env: dict[str, Any]) -> None:
    from app.services.agent_trigger_service import ManualRunner

    c, h = env["client"], env["as"]("admin")
    with Session(env["engine"]) as s:
        rid = uuid4()
        s.execute(
            insert(AgentRun).values(
                run_id=rid,
                agent_name="manual:purchase_order",
                agent_key="purchase_order",
                status="RUNNING",
                trigger_type="MANUAL_DRY_RUN",
                mode="DRY_RUN",
                run_date=env["run_date"],
                cancel_requested=True,
                input_ref={"upstream": [{"agent_key": "stock_balancing", "fresh": True, "action": "RERUN"}]},
            )
        )
        s.commit()
    with sessionmaker(env["engine"])() as s:
        ManualRunner(s).execute(rid)
    assert c.get(f"/api/v1/agent-runs/{rid}", headers=h).json()["run"]["status"] == "CANCELLED"


# --- decisions and outcomes ------------------------------------------------------------------------------------


def test_human_action_updates_the_decision_outcome(env: dict[str, Any]) -> None:
    c = env["client"]
    with Session(env["engine"]) as s:
        sup_c = s.scalar(text("SELECT store_id FROM app_user WHERE username = 'sup.c'"))
        rec_id = s.scalar(
            select(Recommendation.rec_id)
            .where(
                Recommendation.status == "PENDING",
                Recommendation.store_id == sup_c,
                Recommendation.rec_id.in_(select(AgentDecision.rec_id).where(AgentDecision.mode == "LIVE")),
            )
            .limit(1)
        )
    assert rec_id is not None
    r = c.post(
        f"/api/v1/recommendations/{rec_id}/action",
        json={"action": "REJECT", "reason": "No shelf space"},
        headers=env["as"]("sup.c"),
    )
    assert r.status_code == 200, r.text
    with Session(env["engine"]) as s:
        outcome, reason = s.execute(
            select(AgentDecision.outcome, AgentDecision.outcome_reason).where(
                AgentDecision.rec_id == rec_id, AgentDecision.mode == "LIVE"
            )
        ).first()  # type: ignore[misc]
    assert (outcome, reason) == ("REJECTED", "No shelf space")
    stats = c.get("/api/v1/agent-decisions/stats", headers=env["as"]("admin")).json()
    assert any(s["rejected"] >= 1 for s in stats)


def test_decisions_and_runs_page_with_cursors(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    first = c.get("/api/v1/agent-decisions?page_size=5", headers=h).json()
    assert len(first["items"]) == 5 and first["next_cursor"]
    second = c.get(f"/api/v1/agent-decisions?page_size=5&cursor={first['next_cursor']}", headers=h).json()
    assert not {d["decision_id"] for d in first["items"]} & {d["decision_id"] for d in second["items"]}
    runs = c.get("/api/v1/agent-runs?page_size=3&roots_only=true", headers=h).json()
    assert len(runs["items"]) == 3 and all(r["parent_run_id"] is None for r in runs["items"])
    assert c.get("/api/v1/agent-runs?cursor=not-a-cursor", headers=h).status_code == 422


# --- pipeline and graph: skipped stage + failed-then-retried stage --------------------------------------------


class _Flaky(BaseAgent):
    """Sales analytics that fails both attempts of the stage, then succeeds when the coordinator retries it."""

    name = "SalesAnalyticsAgent"
    critical = False
    calls = 0

    def run(self, ctx: RunContext) -> AgentResult:
        type(self).calls += 1
        if type(self).calls <= 2:
            raise TimeoutError("statement timeout on lost-sales query")
        return AgentResult(status="SUCCESS", outputs={"kpis": 0}, step_count=1)


def test_pipeline_and_graph_show_skipped_and_failed_then_retried_stages(env: dict[str, Any]) -> None:
    c, h = env["client"], env["as"]("admin")
    c.patch(
        "/api/v1/agents/related_product", json={"enabled": False, "reason": "Basket data re-check"}, headers=h
    )
    coordinator = RoutedChatLLM(
        {
            "Run Coordinator": ScriptedChatLLM(
                turns=[
                    {"tool_calls": [{"name": "get_exception_summary", "arguments": {}}]},
                    {
                        "tool_calls": [
                            {
                                "name": "submit_plan",
                                "arguments": {
                                    "actions": [
                                        {
                                            "action": "RETRY_AGENT",
                                            "agent_key": "sales_analytics",
                                            "reason": "Timeout looks transient",
                                        },
                                        {
                                            "action": "RETRY_AGENT",
                                            "agent_key": "stock_balancing",
                                            "reason": "should be rejected: critical",
                                        },
                                    ]
                                },
                            }
                        ]
                    },
                ],
                model="openai/gpt-oss-120b",
            )
        }
    )
    _Flaky.calls = 0
    with Session(env["engine"]) as s:
        summary = _orch(
            env, s, chat_llm=coordinator, agent_overrides={"sales_analytics": _Flaky}
        ).run_nightly(run_date=env["run_date"] + timedelta(days=4))
        s.commit()
    run = next(
        r
        for r in c.get("/api/v1/pipeline/runs?page_size=20", headers=h).json()["items"]
        if r["run_id"] == str(summary.run_id)
    )
    st = [(x["agent_key"], x["status"], x["retries"]) for x in run["stages"]]
    assert ("related_product", "SKIPPED_DISABLED", 0) in st
    sa = [x for x in st if x[0] == "sales_analytics"]
    coord = _scalar(
        env,
        select(AgentRun.output_summary).where(
            AgentRun.parent_run_id == summary.run_id, AgentRun.agent_key == "run_coordinator"
        ),
    )
    assert sa[0][1] == "FAILED" and sa[-1][1] == "SUCCESS" and sa[-1][2] >= 1, (
        st,
        coord,
    )  # failed, then retried
    graph = c.get(f"/api/v1/pipeline/runs/{summary.run_id}/graph", headers=h).json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["related_product"]["status"] == "SKIPPED_DISABLED"
    assert nodes["sales_analytics"]["status"] == "SUCCESS" and "retr" in nodes["sales_analytics"]["detail"]
    assert nodes["gate_human"]["node_type"] == "GATE"
    decisions = c.get(
        f"/api/v1/agent-decisions?agent_key=run_coordinator&run_id={summary.run_id}", headers=h
    ).json()["items"]
    assert any(d["decision_type"] == "COORDINATOR_RETRY" for d in decisions)
    out = json.loads(
        _scalar(
            env,
            select(AgentRun.output_summary).where(
                AgentRun.parent_run_id == summary.run_id, AgentRun.agent_key == "run_coordinator"
            ),
        )
    )
    assert any("critical" in r for r in out["rejected"])  # the allow-list blocked retrying a critical agent
    c.patch("/api/v1/agents/related_product", json={"enabled": True, "reason": "Basket data fine"}, headers=h)


# --- Ask RetailPilot and the MCP server ---------------------------------------------------------------------------


def test_ask_is_scoped_cited_and_refuses_actions(env: dict[str, Any]) -> None:
    c = env["client"]
    with Session(env["engine"]) as s:
        sup_a_store = s.scalar(text("SELECT store_id FROM app_user WHERE username = 'sup.a'"))
    a = c.post(
        "/api/v1/assistant/ask", json={"question": "Why are we ordering butter?"}, headers=env["as"]("sup.a")
    ).json()
    for cit in a["citations"]:
        if cit["source_type"] == "RECOMMENDATION":
            assert (
                _scalar(
                    env,
                    select(Recommendation.store_id).where(Recommendation.rec_id == UUID(cit["source_id"])),
                )
                == sup_a_store
            )
    refused = c.post(
        "/api/v1/assistant/ask",
        json={"question": "Approve all purchase orders for my store"},
        headers=env["as"]("sup.a"),
    ).json()
    assert refused["refused"] is True and refused["citations"] == []
    pol = c.post(
        "/api/v1/assistant/ask",
        json={"question": "donor protection transfer policy"},
        headers=env["as"]("sup.b"),
    ).json()
    assert any(x["source_type"] == "POLICY" for x in pol["citations"])
    dec = _scalar_list(
        env, select(AgentDecision.decision_type).where(AgentDecision.agent_key == "ask_retailpilot")
    )
    assert "REQUEST_REFUSED" in dec


def test_mcp_server_lists_scoped_tools_and_never_exposes_actions(env: dict[str, Any]) -> None:
    from app.agents.llm.mcp_server import McpServer

    server = McpServer(sessionmaker(env["engine"]), "sup.a")
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    with Session(env["engine"]) as s:
        donated = (
            select(text("source_rec_id"))
            .select_from(text("transfer_order"))
            .where(text("from_store_id = :own"))
            .params(own=server.store_id)
        )
        other = s.scalar(
            select(Recommendation.rec_id)
            .where(Recommendation.store_id != server.store_id, Recommendation.rec_id.not_in(donated))
            .limit(1)
        )
    lines.append(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_recommendation", "arguments": {"rec_id": str(other)}},
        }
    )
    lines.append(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "approve_purchase_order", "arguments": {}},
        }
    )
    out = io.StringIO()
    server.serve(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"), out)
    replies = {r["id"]: r for r in map(json.loads, out.getvalue().splitlines())}
    assert replies[1]["result"]["protocolVersion"] == "2025-11-25"
    names = {t["name"] for t in replies[2]["result"]["tools"]}
    assert "search_policies" in names and "create_draft_recommendation" not in names
    assert not any(w in n for n in names for w in ("approve", "submit", "dispatch", "receive", "adjust"))
    assert replies[3]["result"]["isError"] is True  # another store's recommendation: not found for this user
    assert replies[4]["result"]["isError"] is True
    _ = datetime.now(UTC)
