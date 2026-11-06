"""Seed the agent layer (D-50): registry, initial on/off config, policy corpus, evaluation results, and — with
`--demo` — real console activity produced by the real code paths (nothing hand-written):

- a toggle history (Related Products off with a reason, then on again);
- a DRY RUN of Stock Balancing (previews only — the inbox does not change);
- three Ask RetailPilot questions (answers with citations, a "not found", a refused action).

    cd backend && uv run python -m scripts.seed_agents [--demo]
seed_demo runs it automatically.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.db import get_sync_engine, get_sync_session_factory
from app.domain.models.agents import AgentConfig, AgentEvalResult, PolicyDocument
from app.domain.models.users import AppUser
from app.services.agent_config_service import snapshot, sync_registry

POLICIES = REPO_ROOT / "data" / "policies"
EVAL_RESULTS = REPO_ROOT / "backend" / "tests" / "agent_evals" / "results.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_policies(session: Session, folder: Path = POLICIES) -> int:
    """One `policy_document` row per `## ` section (full-text indexed by a generated tsvector)."""
    session.execute(delete(PolicyDocument))
    n = 0
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        title = (re.search(r"^# (.+)$", text, re.M) or [None, path.stem])[1]
        for block in re.split(r"^## ", text, flags=re.M)[1:]:
            heading, _, body = block.partition("\n")
            session.add(
                PolicyDocument(
                    section_id=f"{path.stem}#{_slug(heading)}",
                    doc_name=path.stem,
                    title=str(title).strip(),
                    heading=heading.strip(),
                    body=body.strip(),
                )
            )
            n += 1
    session.flush()
    return n


def load_eval_results(session: Session, path: Path = EVAL_RESULTS) -> int:
    """Results written by `python -m scripts.run_agent_evals` (recorded responses, no live model)."""
    if not path.exists():
        return 0
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for row in data.get("results", []):
        session.add(
            AgentEvalResult(
                eval_id=uuid.uuid4(),
                agent_key=row["agent_key"],
                source=row.get("source", "RECORDED"),
                variant=row["variant"],
                cases=row["cases"],
                correctness=Decimal(str(row["correctness"])),
                groundedness=Decimal(str(row["groundedness"])),
                tool_use=Decimal(str(row["tool_use"])),
                failure_handling=Decimal(str(row["failure_handling"])),
                latency_p50_ms=row["latency_p50_ms"],
                latency_p95_ms=row["latency_p95_ms"],
                tokens=row["tokens"],
                est_cost=Decimal(str(row["est_cost_usd"])),
                human_agreement=Decimal(str(row["human_agreement"]))
                if row.get("human_agreement") is not None
                else None,
                details=row.get("details", {}),
            )
        )
        n += 1
    session.flush()
    return n


def toggle(
    session: Session, agent_key: str | None, enabled: bool, reason: str, user_id: uuid.UUID | None
) -> int:
    """Sync equivalent of AgentConfigService (seed / tests): one audited, versioned row."""
    snap = snapshot(session)
    previous = snap.llm_enabled if agent_key is None else snap.enabled.get(agent_key, True)
    version = int(session.scalar(select(func.max(AgentConfig.config_version))) or 0) + 1
    session.add(
        AgentConfig(
            agent_key=agent_key,
            enabled=enabled,
            previous_enabled=previous,
            config_version=version,
            updated_by=user_id,
            reason=reason,
        )
    )
    session.flush()
    return version


def demo_activity(session_factory: Any) -> dict[str, Any]:
    from app.services.agent_trigger_service import ManualRunner
    from app.services.assistant_service import _ask_sync

    out: dict[str, Any] = {}
    with session_factory() as s:
        admin = s.scalar(select(AppUser).where(AppUser.username == "admin"))
        sup = s.scalar(select(AppUser).where(AppUser.username == "sup.c"))
        if admin is None:
            return {"skipped": "no admin user"}
        toggle(
            s,
            "related_product",
            False,
            "Basket data being re-checked after a POS export issue",
            admin.user_id,
        )
        toggle(s, "related_product", True, "Basket data verified — back on", admin.user_id)
        s.commit()
        admin_id, sup_id, sup_store = (
            admin.user_id,
            (sup.user_id if sup else None),
            (sup.store_id if sup else None),
        )

    # dry run of Stock Balancing through the real trigger path (preview only)
    import asyncio

    from app.core.db import get_async_session_factory, use_selector_event_loop
    from app.domain.schemas.agents import TriggerAgentRequest
    from app.services.agent_trigger_service import AgentTriggerService

    async def start() -> uuid.UUID:
        async with get_async_session_factory()() as a:
            user = await a.get(AppUser, admin_id)
            assert user is not None
            res = await AgentTriggerService().start(
                a,
                "stock_balancing",
                TriggerAgentRequest(mode="DRY_RUN", reason="Demo: preview tonight's balancing"),
                user,
            )
            return res.run_id

    use_selector_event_loop()
    run_id = asyncio.run(start())
    with session_factory() as s:
        ManualRunner(s).execute(run_id)
    out["dry_run"] = str(run_id)

    questions = [
        (admin_id, "SUPER_ADMIN", None, "Why are we ordering butter?"),
        (admin_id, "SUPER_ADMIN", None, "What is the approval policy for purchase orders?"),
    ]
    if sup_id:
        questions += [
            (sup_id, "STORE_SUPERVISOR", sup_store, "When must a transfer be received?"),
            (
                sup_id,
                "STORE_SUPERVISOR",
                sup_store,
                "Please approve all pending purchase orders for my store",
            ),
        ]
    out["questions"] = [_ask_sync(u, r, st, q).found for u, r, st, q in questions]
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="also create demo console activity")
    args = parser.parse_args(argv)
    with Session(get_sync_engine()) as s:
        agents = sync_registry(s)
        policies = load_policies(s)
        s.execute(delete(AgentEvalResult))
        evals = load_eval_results(s)
        s.commit()
    print(f"Agents: {agents} registered · policy sections: {policies} · evaluation rows: {evals}")
    if args.demo:
        print(f"Demo agent activity: {demo_activity(get_sync_session_factory())}")


if __name__ == "__main__":
    main()
