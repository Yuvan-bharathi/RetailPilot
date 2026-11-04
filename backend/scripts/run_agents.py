"""Run the RetailPilot AI Multi-Agent Replenishment Pipeline.

Usage:
    uv run python -m scripts.run_agents [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import WorkflowOrchestrator, next_run_date
from app.core.db import get_sync_engine, use_selector_event_loop
from app.domain.models.observability import LLMUsage, ToolCall


def main() -> None:
    use_selector_event_loop()

    parser = argparse.ArgumentParser(description="Trigger the RetailPilot AI agent workflow.")
    parser.add_argument(
        "--date",
        dest="run_date",
        default=None,
        help="Run date (YYYY-MM-DD). Default: the day after the latest loaded POS day.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with Session(engine) as probe:
        target_date = (
            datetime.strptime(args.run_date, "%Y-%m-%d").date() if args.run_date else next_run_date(probe)
        )

    print("=================================================================")
    print("  RetailPilot AI — Autonomous Multi-Agent Replenishment Pipeline ")
    print("=================================================================")
    print(f"Target Run Date : {target_date}")
    print("Starting pipeline orchestrator...\n")

    t0 = time.perf_counter()
    engine = get_sync_engine()

    with Session(engine) as session:
        orchestrator = WorkflowOrchestrator(session)
        summary = orchestrator.run_nightly(run_date=target_date)
        session.commit()  # persist the run (and a FAILED status) — it was never committed before

        # Query LLM usages and tool calls for the run
        llm_usages = (
            session.execute(select(LLMUsage).where(LLMUsage.run_id == summary.run_id)).scalars().all()
        )
        tool_calls = (
            session.execute(select(ToolCall).where(ToolCall.run_id == summary.run_id)).scalars().all()
        )

    duration = time.perf_counter() - t0

    print("=================================================================")
    print("  Pipeline Run Execution Summary")
    print("=================================================================")
    print(f"Run ID           : {summary.run_id}")
    print(f"Status           : {summary.status}")
    print(f"Duration         : {duration:.2f}s")
    print(f"Recommendations  : {summary.recommendations_count}")
    print(f"Purchase Orders  : {summary.po_count}")
    print(f"Stock Transfers  : {summary.transfers_count}")
    print(f"Tool Invocations : {len(tool_calls)}")

    if llm_usages:
        total_prompt = sum(u.input_tokens for u in llm_usages)
        total_completion = sum(u.output_tokens for u in llm_usages)
        print("\n--- Groq LLM Observability ---")
        print(f"Provider         : {llm_usages[0].provider}")
        print(f"Model            : {llm_usages[0].model}")
        print(f"Calls            : {len(llm_usages)}")
        print(f"Prompt Tokens    : {total_prompt}")
        print(f"Generated Tokens : {total_completion}")
        print(f"Total Tokens     : {total_prompt + total_completion}")
    else:
        print("\n(Explanations generated via deterministic grounding templates)")

    if summary.error:
        print(f"\n[ERROR] Pipeline completed with error: {summary.error}")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All agents completed successfully.")
        print("Results are now live on the dashboard (http://127.0.0.1:5173).")


if __name__ == "__main__":
    main()
