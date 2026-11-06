"""Build the demo from the synthetic dataset and the real pipeline (Phase 9, D-47). Nothing is hand-written.

    cd backend && uv run python -m scripts.reset_demo        # empty the business data first (keeps rules, schema)
    cd backend && uv run python -m scripts.seed_demo [--profile small|full] [--no-run]

1. Generate the synthetic dataset (fixed seed; the five scenarios of docs/04-demo-scenarios.md are planted).
2. Bulk-load master data and history (COPY) — app/services/synthetic_loader.py.
3. Create the PoC users (scripts.seed): admin, sup.a, sup.b, sup.c.
4. Register the agents, load the policy corpus and evaluation results (scripts.seed_agents, D-50).
5. Run the nightly pipeline for the dataset's run date (explanations by the configured LLM, else templates).
6. Demo agent-console activity through the real code paths: a toggle history, a dry run, Ask RetailPilot questions.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.orchestrator import WorkflowOrchestrator
from app.core.config import get_settings
from app.core.db import get_sync_engine, get_sync_session_factory
from app.services.pos_source import SyntheticPosSource
from app.services.synthetic_loader import load_synthetic
from data.synthetic.config import GeneratorConfig
from data.synthetic.generate import generate
from data.synthetic.reader import load_dataset
from scripts.seed import seed, seed_password
from scripts.seed_agents import demo_activity
from scripts.seed_agents import main as seed_agents_main


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # small: the five scenarios hold exactly (tested). full: 500 bills/day — scenario 4's bread→butter pair falls
    # below basket.min_support (0.0039 < 0.005), so no co-replenishment there; use it for performance runs (D-47).
    parser.add_argument("--profile", default="small", choices=["full", "small", "tiny"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--no-run", action="store_true", help="load data only; do not run the nightly pipeline"
    )
    args = parser.parse_args(argv)

    engine = get_sync_engine()
    with Session(engine) as session:
        if session.scalar(text("SELECT count(*) FROM sales_transaction")):
            raise SystemExit(
                "The database already holds sales data — run `python -m scripts.reset_demo` first."
            )

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        manifest = generate(GeneratorConfig(profile=args.profile, seed=args.seed), Path(tmp))
        ds = load_dataset(Path(tmp))
    print(f"Generated the {args.profile} dataset in {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    with Session(engine) as session:
        report = load_synthetic(session, ds)
        session.commit()
    print(
        f"Loaded {report.stores} stores, {report.products} products, {report.bills:,} bills, {report.lines:,} lines, "
        f"{report.movements:,} movements ({report.reconciliation_adjustments} reconciliation adjustments) "
        f"in {time.perf_counter() - t0:.1f}s"
    )
    users = seed(engine, seed_password(get_settings()))
    print(f"Users: {users.users_created} created (admin, sup.a, sup.b, sup.c)")

    seed_agents_main([])

    if args.no_run:
        return
    run_date = date.fromisoformat(manifest["run_date"])
    t0 = time.perf_counter()
    with Session(engine) as session:
        summary = WorkflowOrchestrator(
            session, pos_source=SyntheticPosSource(ds), commit_per_stage=True
        ).run_nightly(run_date=run_date)
        session.commit()
    print(
        f"Nightly run {run_date}: {summary.status} in {time.perf_counter() - t0:.1f}s — "
        f"{summary.recommendations_count} recommendations, {summary.transfers_count} transfers, "
        f"{summary.po_count} purchase orders"
    )
    if summary.error:
        raise SystemExit(f"Run failed: {summary.error}")
    print(f"Demo agent activity: {demo_activity(get_sync_session_factory())}")


if __name__ == "__main__":
    main()
