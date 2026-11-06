"""Run the Objective III evaluation (docs/08 §7, D-50) and write the report.

    cd backend && uv run python -m scripts.run_agent_evals            # scripted replays (no live model), default
    cd backend && uv run python -m scripts.run_agent_evals --live     # the same inputs against Groq (manual, costs)

Needs the demo database (scripts.seed_demo). Every case runs inside a rolled-back savepoint. Writes:
- backend/tests/agent_evals/results.json (loaded into `agent_eval_result` by scripts.seed_agents),
- docs/notes/agent-eval-report.md,
- `agent_eval_result` rows (shown on each agent's detail page).
Live mode also runs the LLM-as-judge rubric (tests/agent_evals/judge_rubric.md) on Ask answers and, when
tests/agent_evals/human_review.json holds a reviewer's labels, records judge–human agreement.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.db import get_sync_engine
from app.domain.models.agents import AgentEvalResult
from scripts.seed_agents import EVAL_RESULTS, load_eval_results
from tests.agent_evals import cases as C  # noqa: N812

REPORT = REPO_ROOT / "docs" / "notes" / "agent-eval-report.md"
HUMAN = REPO_ROOT / "backend" / "tests" / "agent_evals" / "human_review.json"
NAMES = {
    "ask_retailpilot": "Ask RetailPilot (retrieval)",
    "data_quality": "Data Quality (validation)",
    "replenishment_action": "Replenishment Action (action, drafts only)",
    "run_coordinator": "Run Coordinator (coordinator)",
    "recommendation_reviewer": "Recommendation Reviewer (reviewer)",
}


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def human_agreement(results: list[C.CaseResult]) -> dict[str, float]:
    """Agreement of the judge with a human reviewer's labels (only labels the reviewer actually filled in)."""
    if not HUMAN.exists():
        return {}
    labels = json.loads(HUMAN.read_text(encoding="utf-8")).get("labels", {})
    out: dict[str, float] = {}
    for agent in {r.agent for r in results}:
        pairs = [
            (r.outcome.correct, labels[f"{agent}/{r.name}"])
            for r in results
            if r.variant == "AGENT" and r.agent == agent and isinstance(labels.get(f"{agent}/{r.name}"), bool)
        ]
        if pairs:
            out[agent] = sum(a == b for a, b in pairs) / len(pairs)
    return out


def write_report(rows: list[dict[str, Any]], results: list[C.CaseResult], source: str) -> None:
    lines = [
        "# Agent evaluation report (Objective III)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `python -m scripts.run_agent_evals"
        f"{' --live' if source == 'LIVE' else ''}` — source **{source}**.",
        "",
        "- **RECORDED** = scripted model replays (hand-authored tool-call turns, no live model) — they test the",
        "  framework, tools, code checks, stopping conditions and failure handling deterministically in CI. They do",
        "  NOT measure the live model's judgement; run `--live` for that (manual, logged, costs tokens).",
        "- **BASELINE** = the deterministic path on the same inputs (no LLM).",
        "- Tokens and cost of RECORDED runs are the scripted token counts priced as `openai/gpt-oss-120b`",
        "  — an estimate of what a live run of the same turns would cost, not a measurement.",
        "- Human agreement: filled only when a reviewer has labelled cases in `tests/agent_evals/human_review.json`.",
        "",
        "| Agent | Variant | Cases | Correct | Grounded | Tool use | Failure handling | p50 / p95 | Tokens | Est. cost | Human agreement |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {NAMES.get(r['agent_key'], r['agent_key'])} | {r['variant']} | {r['cases']} | {pct(r['correctness'])} | "
            f"{pct(r['groundedness'])} | {pct(r['tool_use'])} | {pct(r['failure_handling'])} | "
            f"{r['latency_p50_ms']} / {r['latency_p95_ms']} ms | {r['tokens']:,} | ${r['est_cost_usd']} | "
            f"{pct(r['human_agreement']) if r['human_agreement'] is not None else 'pending'} |"
        )
    lines += ["", "## Cases", ""]
    for agent in NAMES:
        lines += [
            f"### {NAMES[agent]}",
            "",
            "| Case | Category | Agent | Baseline | Agent detail |",
            "|---|---|---|---|---|",
        ]
        for r in [x for x in results if x.agent == agent and x.variant == "AGENT"]:
            base = next(
                (b for b in results if b.agent == agent and b.name == r.name and b.variant == "BASELINE"),
                None,
            )
            lines.append(
                f"| {r.name} | {r.category} | {'pass' if r.outcome.correct else 'FAIL'} | "
                f"{'pass' if base and base.outcome.correct else 'fail'} | {r.outcome.detail.replace('|', '/')} |"
            )
        lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--live", action="store_true", help="use the configured Groq model instead of replays"
    )
    args = parser.parse_args(argv)
    source = "RECORDED"
    if args.live:
        from app.agents.llm.agents import make_chat_llm

        live = make_chat_llm()
        if live is None:
            raise SystemExit("--live needs GROQ_API_KEY and LLM_PROVIDER=groq")
        C.LIVE_LLM = live
        source = "LIVE"
    engine = get_sync_engine()
    with Session(engine) as s:
        results = C.run_all(s)
        s.rollback()
    rows = C.summarize(results)
    agreement = human_agreement(results)
    for r in rows:
        r["source"] = source
        if r["variant"] == "AGENT" and r["agent_key"] in agreement:
            r["human_agreement"] = round(agreement[r["agent_key"]], 4)
    Path(EVAL_RESULTS).write_text(
        json.dumps({"generated": datetime.now(UTC).isoformat(), "source": source, "results": rows}, indent=2),
        encoding="utf-8",
    )
    write_report(rows, results, source)
    with Session(engine) as s:
        s.execute(delete(AgentEvalResult).where(AgentEvalResult.source == source))
        load_eval_results(s)
        s.commit()
    for r in rows:
        print(
            f"{r['agent_key']:<24} {r['variant']:<8} correct {pct(r['correctness']):>4}  grounded {pct(r['groundedness']):>4}"
            f"  failure handling {pct(r['failure_handling']):>4}  tokens {r['tokens']:>7,}"
        )
    print(f"Wrote {REPORT.relative_to(REPO_ROOT)} and {Path(EVAL_RESULTS).relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
