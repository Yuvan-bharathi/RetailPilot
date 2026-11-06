"""Objective III evaluation harness in CI (docs/08 §7): scripted model replays, no live model. The thresholds are
the acceptance bar of the agents (code checks); the numbers themselves are reported by scripts.run_agent_evals."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tests.agent_evals.cases import ALL_CASES, CaseResult, run_all, summarize
from tests.scenarios.test_agent_console import env  # noqa: F401 — reuse the seeded module database

pytestmark = pytest.mark.scenario


@pytest.fixture(scope="module")
def results(env: dict[str, Any]) -> Iterator[list[CaseResult]]:  # noqa: F811
    engine: Engine = env["engine"]
    with Session(engine) as s:
        yield run_all(s)


def test_at_least_ten_cases_per_agent_and_every_category() -> None:
    by: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for c in ALL_CASES:
        by.setdefault(c.agent, set()).add(c.category)
        counts[c.agent] = counts.get(c.agent, 0) + 1
    assert set(counts) == {
        "ask_retailpilot",
        "data_quality",
        "replenishment_action",
        "run_coordinator",
        "recommendation_reviewer",
    }
    assert all(n >= 10 for n in counts.values()), counts
    for agent, cats in by.items():
        assert {"normal", "invalid_input", "tool_failure"} <= cats, (agent, cats)
    every = set().union(*by.values())
    assert {"normal", "ambiguous", "missing_data", "invalid_input", "tool_failure", "unsafe"} <= every


def test_every_agent_case_passes_its_code_checks(results: list[CaseResult]) -> None:
    failed = [
        (r.agent, r.name, r.outcome.detail) for r in results if r.variant == "AGENT" and not r.outcome.correct
    ]
    assert not failed, failed


def test_no_disallowed_tool_was_ever_executed(results: list[CaseResult]) -> None:
    assert all(r.outcome.tool_use for r in results), [
        (r.agent, r.name) for r in results if not r.outcome.tool_use
    ]


def test_agent_outputs_are_grounded_or_rejected(results: list[CaseResult]) -> None:
    bad = [
        (r.agent, r.name)
        for r in results
        if r.variant == "AGENT" and not r.outcome.grounded and r.name != "hallucinated_number"
    ]  # that case is the code check rejecting an invented number
    assert not bad, bad


def test_summary_has_both_variants(results: list[CaseResult]) -> None:
    rows = summarize(results)
    assert {(r["agent_key"], r["variant"]) for r in rows} == {
        (a, v) for a in {c.agent for c in ALL_CASES} for v in ("AGENT", "BASELINE")
    }
