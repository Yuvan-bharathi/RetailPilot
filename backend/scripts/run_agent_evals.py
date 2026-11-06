"""Run the Objective III evaluation (docs/08 §7, D-50, D-55) and write the report.

    cd backend && uv run python -m scripts.run_agent_evals              # scripted replays, no live model (CI)
    cd backend && uv run python -m scripts.run_agent_evals --live       # Anthropic (claude-opus-5-5), manual, costs
    cd backend && uv run python -m scripts.run_agent_evals --agreement  # after labelling: judge–human agreement

Needs the demo database (scripts.seed_demo). Every case runs inside a rolled-back savepoint.

--live needs LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY. It runs every case that does not inject a model fault
(cases.SCRIPTED_ONLY) with the real model, records per agent correctness, groundedness, tool use, failures handled,
p50/p95 latency, tokens and cost (provider usage incl. cache pricing), then grades a stratified sample of 20 agent
outputs with a SEPARATE judge prompt (tests/agent_evals/judge_rubric.md) and writes them to the labelling sheet
backend/tests/agent_evals/human_labels.csv — fill `human_label` (acceptable / not_acceptable) and run --agreement.
Writes results.json (loaded into `agent_eval_result`), docs/notes/agent-eval-report.md and the DB rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
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
SHEET = REPO_ROOT / "backend" / "tests" / "agent_evals" / "human_labels.csv"
RUBRIC = REPO_ROOT / "backend" / "tests" / "agent_evals" / "judge_rubric.md"
SAMPLE_SIZE = 20
NAMES = {
    "ask_retailpilot": "Ask RetailPilot (retrieval)",
    "data_quality": "Data Quality (validation)",
    "replenishment_action": "Replenishment Action (action, drafts only)",
    "run_coordinator": "Run Coordinator (coordinator)",
    "recommendation_reviewer": "Recommendation Reviewer (reviewer)",
}
COLUMNS = [
    "sample_id",
    "source",
    "agent_key",
    "case",
    "category",
    "input",
    "agent_output",
    "code_check",
    "judge_verdict",
    "judge_reason",
    "human_label",
    "human_notes",
]
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"acceptable": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["acceptable", "reason"],
    "additionalProperties": False,
}


def pct(x: float | None) -> str:
    return "pending" if x is None else f"{x * 100:.0f}%"


def sample(results: list[C.CaseResult], n: int = SAMPLE_SIZE) -> list[C.CaseResult]:
    """Stratified, reproducible: an equal share per agent (4 each for 5 agents), seed 42."""
    rng = random.Random(42)
    agents = list(NAMES)
    out: list[C.CaseResult] = []
    for i, agent in enumerate(agents):
        pool = [r for r in results if r.agent == agent and r.variant == "AGENT"]
        k = n // len(agents) + (1 if i < n % len(agents) else 0)
        out += rng.sample(pool, min(k, len(pool)))
    return out


def judge(rows: list[C.CaseResult], json_llm: Any) -> dict[tuple[str, str], tuple[str, str]]:
    """LLM-as-judge with its own prompt and rubric (never the agent's prompt)."""
    system = RUBRIC.read_text(encoding="utf-8")
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for r in rows:
        user = json.dumps(
            {
                "agent": NAMES[r.agent],
                "asked": r.outcome.input_text or r.name,
                "output": r.outcome.output_text or r.outcome.detail,
            },
            ensure_ascii=False,
        )
        try:
            reply = json_llm.complete_json(system, user, "judge_verdict", JUDGE_SCHEMA)
            out[(r.agent, r.name)] = (
                "acceptable" if reply.data.get("acceptable") else "not_acceptable",
                str(reply.data.get("reason", ""))[:300],
            )
        except Exception as e:  # a judge failure is recorded, never guessed
            out[(r.agent, r.name)] = ("judge_error", type(e).__name__)
    return out


def write_sheet(
    rows: list[C.CaseResult], verdicts: dict[tuple[str, str], tuple[str, str]], source: str
) -> Path:
    path = SHEET
    if path.exists() and any(r.get("human_label") for r in csv.DictReader(path.open(encoding="utf-8"))):
        path = SHEET.with_name(f"human_labels-{datetime.now(UTC):%Y%m%d-%H%M}.csv")  # never overwrite labels
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for i, r in enumerate(rows, 1):
            verdict, reason = verdicts.get((r.agent, r.name), ("", "no judge (scripted run)"))
            w.writerow(
                {
                    "sample_id": i,
                    "source": source,
                    "agent_key": r.agent,
                    "case": r.name,
                    "category": r.category,
                    "input": r.outcome.input_text or r.name,
                    "agent_output": r.outcome.output_text or r.outcome.detail,
                    "code_check": "pass" if r.outcome.correct else "fail",
                    "judge_verdict": verdict,
                    "judge_reason": reason,
                    "human_label": "",
                    "human_notes": "",
                }
            )
    return path


def agreement(path: Path = SHEET) -> dict[str, dict[str, float | int | None]]:
    """Per agent and overall: judge–human and code-check–human agreement over labelled rows."""
    rows = [
        r
        for r in csv.DictReader(path.open(encoding="utf-8"))
        if r.get("human_label") in ("acceptable", "not_acceptable")
    ]
    out: dict[str, dict[str, float | int | None]] = {}
    for agent in [*NAMES, "overall"]:
        rs = rows if agent == "overall" else [r for r in rows if r["agent_key"] == agent]
        judged = [r for r in rs if r["judge_verdict"] in ("acceptable", "not_acceptable")]
        out[agent] = {
            "labelled": len(rs),
            "judge_agreement": (sum(r["judge_verdict"] == r["human_label"] for r in judged) / len(judged))
            if judged
            else None,
            "code_check_agreement": (
                sum((r["code_check"] == "pass") == (r["human_label"] == "acceptable") for r in rs) / len(rs)
            )
            if rs
            else None,
        }
    return out


def write_report(
    rows: list[dict[str, Any]],
    results: list[C.CaseResult],
    source: str,
    agree: dict[str, dict[str, float | int | None]] | None = None,
) -> None:
    live = source == "LIVE"
    lines = [
        "# Agent evaluation report (Objective III)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `python -m scripts.run_agent_evals"
        f"{' --live' if live else ''}` — source **{source}**.",
        "",
        "- **LIVE** = the configured Anthropic model (D-53) on every case that does not inject a model fault; tokens,"
        " cost and latency are measured from the provider's usage."
        if live
        else "- **RECORDED** = scripted model replays (hand-authored tool-call turns, no live model): they test the"
        " framework, tools, code checks, stopping conditions and failure handling in CI. They do NOT measure the"
        " live model's judgement — run `--live` for that (manual, costs tokens).",
        "- **BASELINE** = the deterministic path on the same inputs (no LLM).",
        ""
        if live
        else "- Tokens/cost of RECORDED runs are scripted token counts priced as `claude-opus-5-5` — an"
        " estimate, not a measurement. Latency excludes model time.",
        "- Human agreement: from `backend/tests/agent_evals/human_labels.csv` after a reviewer labels it"
        " (`--agreement`).",
        "",
        "| Agent | Variant | Cases | Correct | Grounded | Tool use | Failure handling | p50 / p95 | Tokens | Est. cost |"
        " Judge–human agreement |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {NAMES.get(r['agent_key'], r['agent_key'])} | {r['variant']} | {r['cases']} | {pct(r['correctness'])}"
            f" | {pct(r['groundedness'])} | {pct(r['tool_use'])} | {pct(r['failure_handling'])} | "
            f"{r['latency_p50_ms']} / {r['latency_p95_ms']} ms | {r['tokens']:,} | ${r['est_cost_usd']} | "
            f"{pct(r['human_agreement'])} |"
        )
    if agree:
        lines += [
            "",
            "## Human review",
            "",
            "| Agent | Labelled | Judge–human | Code check–human |",
            "|---|---:|---:|---:|",
        ]
        for k, v in agree.items():
            lines.append(
                f"| {NAMES.get(k, k)} | {v['labelled']} | {pct(v['judge_agreement'])} | "
                f"{pct(v['code_check_agreement'])} |"
            )
    lines += ["", "## Cases", ""]
    for agent in NAMES:
        lines += [
            f"### {NAMES[agent]}",
            "",
            "| Case | Category | Agent | Baseline | Agent detail |",
            "|---|---|---|---|---|",
        ]
        for res in [x for x in results if x.agent == agent and x.variant == "AGENT"]:
            base = next(
                (b for b in results if b.agent == agent and b.name == res.name and b.variant == "BASELINE"),
                None,
            )
            lines.append(
                f"| {res.name} | {res.category} | {'pass' if res.outcome.correct else 'FAIL'} | "
                f"{'pass' if base and base.outcome.correct else 'fail'} | {res.outcome.detail.replace('|', '/')} |"
            )
        lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def store(rows: list[dict[str, Any]], source: str) -> None:
    """results.json keeps the latest rows of EACH source (RECORDED and LIVE); the DB mirrors it."""
    path = Path(EVAL_RESULTS)
    kept = []
    if path.exists():
        kept = [
            r
            for r in json.loads(path.read_text(encoding="utf-8")).get("results", [])
            if r.get("source") != source
        ]
    path.write_text(
        json.dumps({"generated": datetime.now(UTC).isoformat(), "results": kept + rows}, indent=2),
        encoding="utf-8",
    )
    with Session(get_sync_engine()) as s:
        s.execute(delete(AgentEvalResult))
        load_eval_results(s)
        s.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--live", action="store_true", help="run on the configured Anthropic model (manual, costs)"
    )
    parser.add_argument(
        "--agreement", action="store_true", help="compute judge–human agreement from the sheet"
    )
    args = parser.parse_args(argv)

    if args.agreement:
        agree = agreement()
        data = json.loads(Path(EVAL_RESULTS).read_text(encoding="utf-8"))
        sheet_source = next(csv.DictReader(SHEET.open(encoding="utf-8")), {}).get("source", "LIVE")
        rows = [r for r in data["results"] if r.get("source") == sheet_source]
        for r in rows:
            if r["variant"] == "AGENT":
                r["human_agreement"] = agree.get(r["agent_key"], {}).get("judge_agreement")
        store(rows, sheet_source)
        print(json.dumps(agree, indent=2))
        print("Stored judge–human agreement; re-run the evaluation to refresh the report tables.")
        return

    source = "RECORDED"
    json_llm = None
    if args.live:
        from app.core.config import get_settings
        from app.services.llm_factory import make_chat_llm, make_json_llm

        settings = get_settings()
        if settings.llm_provider != "anthropic":
            raise SystemExit("--live runs on Anthropic (D-53): set LLM_PROVIDER=anthropic")
        C.LIVE_LLM, json_llm = make_chat_llm(settings), make_json_llm(settings)
        if C.LIVE_LLM is None or json_llm is None:
            raise SystemExit("--live needs ANTHROPIC_API_KEY")
        C.LIVE_JSON = json_llm
        source = "LIVE"
    engine = get_sync_engine()
    with Session(engine) as s:
        results = C.run_all(s)
        s.rollback()
    rows = C.summarize(results)
    for r in rows:
        r["source"] = source
    picked = sample(results)
    verdicts = judge(picked, json_llm) if json_llm is not None else {}
    sheet = write_sheet(picked, verdicts, source)
    labels = agreement(sheet) if sheet.exists() else None
    for r in rows:
        if labels and r["variant"] == "AGENT":
            r["human_agreement"] = labels.get(r["agent_key"], {}).get("judge_agreement")
    store(rows, source)
    write_report(rows, results, source, labels if labels and labels["overall"]["labelled"] else None)
    for r in rows:
        print(
            f"{r['agent_key']:<24} {r['variant']:<8} correct {pct(r['correctness']):>4}  grounded "
            f"{pct(r['groundedness']):>4}  failures {pct(r['failure_handling']):>4}  "
            f"p50/p95 {r['latency_p50_ms']}/{r['latency_p95_ms']} ms  tokens {r['tokens']:>7,}  ${r['est_cost_usd']}"
        )
    print(
        f"Wrote {REPORT.relative_to(REPO_ROOT)}, {Path(EVAL_RESULTS).relative_to(REPO_ROOT)} and "
        f"{sheet.relative_to(REPO_ROOT)} ({len(picked)} outputs to label)"
    )


if __name__ == "__main__":
    main()
