"""Human-labelling sheet and judge–human agreement (docs/08 §7, D-55)."""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.run_agent_evals import COLUMNS, NAMES, agreement, sample
from tests.agent_evals.cases import CaseResult, Outcome


def _res(agent: str, i: int) -> CaseResult:
    return CaseResult(agent, f"case{i}", "normal", "AGENT", Outcome(True, True, True), 1)


def test_sample_is_stratified_and_reproducible() -> None:
    results = [_res(a, i) for a in NAMES for i in range(10)]
    a, b = sample(results), sample(results)
    assert len(a) == 20 and [(r.agent, r.name) for r in a] == [(r.agent, r.name) for r in b]
    assert {r.agent for r in a} == set(NAMES) and all(sum(r.agent == k for r in a) == 4 for k in NAMES)


def test_agreement_counts_only_labelled_rows(tmp_path: Path) -> None:
    rows = [
        ("ask_retailpilot", "pass", "acceptable", "acceptable"),
        ("ask_retailpilot", "pass", "not_acceptable", "acceptable"),
        ("ask_retailpilot", "fail", "not_acceptable", "not_acceptable"),
        ("data_quality", "pass", "acceptable", ""),  # not labelled yet
    ]
    path = tmp_path / "s.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for i, (agent, code, judge, human) in enumerate(rows):
            w.writerow(
                {
                    "sample_id": i,
                    "agent_key": agent,
                    "code_check": code,
                    "judge_verdict": judge,
                    "human_label": human,
                }
            )
    agree = agreement(path)
    assert agree["ask_retailpilot"] == {"labelled": 3, "judge_agreement": 2 / 3, "code_check_agreement": 1.0}
    assert agree["data_quality"]["labelled"] == 0 and agree["data_quality"]["judge_agreement"] is None
    assert agree["overall"]["labelled"] == 3
