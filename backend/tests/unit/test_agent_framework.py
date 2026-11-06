"""Tool-loop framework and registry (docs/08 §4–5, D-50) — no database, no live model."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.llm.chat import ScriptedChatLLM
from app.agents.llm.framework import Limits, ToolContext, ToolError, ToolLoopAgent, ToolSpec
from app.agents.llm.tools import TOOLS
from app.agents.registry import AGENTS, BY_KEY, LLM_KEYS, downstream_dependants, upstream_closure
from app.core.config import REPO_ROOT


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1)


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int


def _double(ctx: ToolContext, a: Args) -> dict[str, Any]:
    if a.x < 0:
        raise ToolError("x must be positive")
    if a.x == 13:
        raise RuntimeError("boom")
    return {"value": a.x * 2}


TOOL = ToolSpec("double", "Double a number.", Args, "READ", _double)


def agent(
    turns: list[Any], limits: Limits | None = None, raise_on: set[int] | None = None
) -> ToolLoopAgent[Out]:
    return ToolLoopAgent(
        agent_key="t",
        system_prompt="sys",
        tools=[TOOL],
        submit_name="submit",
        submit_description="submit",
        output_model=Out,
        limits=limits or Limits(),
        llm=ScriptedChatLLM(turns=turns, raise_on=raise_on or set()),
        logger=None,
    )


def ctx() -> ToolContext:
    return ToolContext(session=cast(Session, None), role="SUPER_ADMIN", store_id=None, run_id=uuid4())


def c(name: str, **args: Any) -> dict[str, Any]:
    return {"tool_calls": [{"name": name, "arguments": args}]}


def test_tool_then_submit_produces_validated_output_and_remembers_numbers() -> None:
    cx = ctx()
    r = agent([c("double", x=21), c("submit", answer="42")]).run(cx, "task")
    assert r.stop_reason == "submitted" and r.output == Out(answer="42")
    assert r.tool_sequence == ["double", "submit"] and r.llm_calls == 2 and r.tokens > 0
    assert 42 in {int(n) for n in cx.seen_numbers}


def test_invalid_output_retries_once_then_fails_safe() -> None:
    r = agent([c("submit", answer=""), c("submit", answer="ok")]).run(ctx(), "t")
    assert r.output == Out(answer="ok")
    r = agent([c("submit", answer=""), c("submit", wrong=1)]).run(ctx(), "t")
    assert r.output is None and r.stop_reason == "invalid_output"


def test_disallowed_tool_is_refused_not_executed() -> None:
    r = agent([c("approve_purchase_order", po_id="1"), c("submit", answer="no")]).run(ctx(), "t")
    assert r.tools[0].status == "ERROR" and "not allowed" in str(r.tools[0].result)
    assert r.output is not None


def test_tool_errors_are_defined_outcomes() -> None:
    r = agent([c("double", x=-1), c("double", x=13), c("double", y=1), c("submit", answer="done")]).run(
        ctx(), "t"
    )
    assert [t.status for t in r.tools] == ["ERROR", "ERROR", "ERROR", "OK"]
    assert "tool failed (RuntimeError)" in str(r.tools[1].result)


def test_stopping_conditions() -> None:
    assert agent([c("double", x=1)] * 20, Limits(max_tool_calls=2)).run(ctx(), "t").stop_reason in (
        "max_tool_calls",
        "max_turns",
    )
    assert (
        agent([c("double", x=1)] * 5, Limits(max_tokens=1_500)).run(ctx(), "t").stop_reason == "token_budget"
    )
    assert agent([c("double", x=1)] * 5, Limits(timeout_s=-1)).run(ctx(), "t").stop_reason == "timeout"
    assert agent([{"content": "hi"}, {"content": "hi"}]).run(ctx(), "t").stop_reason == "no_submit"
    r = agent([], raise_on={0}).run(ctx(), "t")
    assert r.stop_reason == "model_error" and r.output is None


def test_registry_cards_prompts_and_dependencies() -> None:
    assert len(AGENTS) == 11 and len(LLM_KEYS) == 5
    assert {a.pattern for a in AGENTS if a.kind == "LLM"} == {
        "RETRIEVAL",
        "VALIDATION",
        "ACTION",
        "COORDINATOR",
        "REVIEWER",
    }
    for a in AGENTS:
        assert (REPO_ROOT / a.card_path).exists(), a.card_path
        if a.kind == "LLM":
            assert (REPO_ROOT / "backend/app/agents/llm/prompts" / f"{a.prompt_version}.md").exists()
        for t in (*a.read_tools, *a.draft_tools):
            if a.kind == "LLM":
                assert t in TOOLS, (a.key, t)
        for d in a.depends_on:
            assert d in BY_KEY
    assert upstream_closure("purchase_order") == ["demand_forecasting", "stock_balancing"]
    assert set(downstream_dependants("demand_forecasting")) >= {
        "stock_balancing",
        "freshness",
        "purchase_order",
    }


def test_no_tool_can_perform_a_consequential_action() -> None:
    forbidden = (
        "approve",
        "submit",
        "dispatch",
        "receive",
        "release",
        "adjust",
        "set_rule",
        "update_stock",
        "delete",
    )
    assert not [n for n in TOOLS if any(f in n for f in forbidden)]
    assert {t.kind for t in TOOLS.values()} == {"READ", "DRAFT_WRITE"}
    assert all(n.startswith("create_") for n, t in TOOLS.items() if t.kind == "DRAFT_WRITE")
