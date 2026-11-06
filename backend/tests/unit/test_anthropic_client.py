"""Anthropic provider adapter (D-53) — fake SDK client, no network."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.agents.llm.framework import Limits, ToolContext, ToolLoopAgent
from app.core.config import Settings
from app.services.anthropic_client import (
    AnthropicChatClient,
    AnthropicJsonClient,
    cost_of,
    to_anthropic_messages,
)
from app.services.llm_client import LLMError
from app.services.llm_factory import make_chat_llm, make_json_llm
from tests.unit.test_agent_framework import TOOL, Out


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return self.responses.pop(0)


def fake(responses: list[Any]) -> Any:
    msgs = FakeMessages(responses)
    return NS(beta=NS(messages=msgs)), msgs


def usage(i: int = 100, o: int = 20, cw: int = 0, cr: int = 0) -> Any:
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=cw, cache_read_input_tokens=cr)


def resp(content: list[Any], stop: str = "end_turn", model: str = "claude-opus-5-5") -> Any:
    return NS(content=content, stop_reason=stop, model=model, usage=usage())


S = Settings(llm_provider="anthropic", anthropic_api_key="k")  # type: ignore[arg-type]


def test_factory_defaults_to_anthropic_and_falls_back_to_none_without_key() -> None:
    assert Settings.model_fields["llm_provider"].default == "anthropic"
    assert isinstance(make_chat_llm(S), AnthropicChatClient)
    assert isinstance(make_json_llm(S), AnthropicJsonClient)
    assert make_chat_llm(Settings(llm_provider="anthropic", anthropic_api_key=None)) is None
    assert make_chat_llm(Settings(llm_provider="template")) is None


def test_tool_loop_on_claude_echoes_raw_content_and_groups_tool_results() -> None:
    thinking = NS(type="thinking", thinking="", signature="sig")
    turn1 = resp([thinking, NS(type="tool_use", id="tu1", name="double", input={"x": 21})], "tool_use")
    turn2 = resp([NS(type="tool_use", id="tu2", name="submit", input={"answer": "42"})], "tool_use")
    client, msgs = fake([turn1, turn2])
    llm = AnthropicChatClient(S, client=client)
    agent = ToolLoopAgent(
        agent_key="t",
        system_prompt="sys",
        tools=[TOOL],
        submit_name="submit",
        submit_description="d",
        output_model=Out,
        limits=Limits(),
        llm=llm,
        logger=None,
    )
    ctx = ToolContext(session=None, role="SUPER_ADMIN", store_id=None, run_id=__import__("uuid").uuid4())  # type: ignore[arg-type]
    r = agent.run(ctx, "task")
    assert r.output == Out(answer="42") and r.llm_calls == 2
    first, second = msgs.calls
    assert first["system"] == "sys" and first["model"] == "claude-opus-5-5"
    assert "temperature" not in first and "thinking" not in first and "tool_choice" not in first
    assert first["output_config"] == {"effort": "medium"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in first["tools"]} == {"double", "submit"} and "input_schema" in first["tools"][0]
    m = second["messages"]
    assert m[1]["role"] == "assistant" and m[1]["content"] == turn1.content  # verbatim, thinking included
    assert m[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": '{"value":42}'}],
    }


def test_errors_refusal_and_cost() -> None:
    client, _ = fake([resp([], "refusal")])
    with pytest.raises(LLMError, match="refusal"):
        AnthropicChatClient(S, client=client).chat([{"role": "system", "content": "s"}], [])
    tin, tout, usd = cost_of("claude-opus-5-5", usage(1_000_000, 100_000, 0, 1_000_000))
    assert (tin, tout) == (2_000_000, 100_000) and usd == Decimal("4") + Decimal("2") + Decimal("0.20")


def test_json_client_parses_constrained_output() -> None:
    client, msgs = fake([resp([NS(type="text", text=json.dumps({"explanations": []}))])])
    reply = AnthropicJsonClient(S, client=client).complete_json("sys", "u", "x", {"type": "object"})
    assert reply.data == {"explanations": []} and reply.est_cost > 0
    assert msgs.calls[0]["output_config"]["format"] == {"type": "json_schema", "schema": {"type": "object"}}


def test_neutral_transcript_conversion() -> None:
    system, m = to_anthropic_messages(
        [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "Q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "t", "arguments": '{"q": 1}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "a", "content": "ERROR: nope"},
            {"role": "user", "content": "Finish by calling submit."},
        ]
    )
    assert system == "S"
    assert m[1]["content"] == [{"type": "tool_use", "id": "a", "name": "t", "input": {"q": 1}}]
    assert m[2]["content"][0]["is_error"] is True and m[2]["content"][1]["type"] == "text"
