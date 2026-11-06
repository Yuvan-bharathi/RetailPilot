"""Anthropic (Claude) provider — the default LLM provider (D-53). Official `anthropic` SDK, Messages API.

Same contracts as the Groq clients, so callers never see the provider:
- `AnthropicJsonClient.complete_json` (JsonLLM): explanations and the reviewer's judge. JSON is constrained with
  `output_config.format` (json_schema); the reply's first text block is the JSON object.
- `AnthropicChatClient.chat` (ChatLLM): the agents' tool loop. Tools are sent in Anthropic shape; `tool_use` blocks
  come back as ToolCallRequest; the agent ends by calling its submit tool. The assistant `content` is kept verbatim
  (`ChatTurn.raw`) and echoed back unchanged on the next turn — thinking blocks and any `fallback` marker must not be
  edited (preserved thinking). Tool results go back as `tool_result` blocks in ONE user message.

Request choices for `claude-opus-5-5`: no `temperature` / `thinking` parameters (thinking is always on; depth is
`output_config.effort`, default `medium`, set explicitly); `tool_choice` auto (forced tool choice is a 400 on this
model — the prompt names the submit tool and the loop nudges once); top-level `cache_control` caches the stable
system + tools prefix; server-side refusal fallback `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`)
so a classifier decline is re-run on Anthropic's recommended model instead of failing. A final `refusal` or a
`max_tokens` stop is an error → the agent's deterministic fail-safe.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import anthropic

from app.agents.llm.chat import ChatTurn, ToolCallRequest
from app.core.config import Settings
from app.core.logging import get_logger
from app.services.llm_client import LLMError, LLMReply

logger = get_logger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: USD per 1M tokens: (input, output, cache read). Cache writes cost 1.25 × input. Checked 2026-11-06 against the
#: Claude API skill's model table; a fallback answer is priced by the model that served it (response.model).
PRICES: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20")),
    "claude-opus-5": (Decimal("5"), Decimal("25"), Decimal("0.50")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10"), Decimal("0.20")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01")),
}


def cost_of(model: str, usage: Any) -> tuple[int, int, Decimal]:
    """(input tokens incl. cache, output tokens, USD) for a response's usage."""
    plain = int(getattr(usage, "input_tokens", 0) or 0)
    written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    p_in, p_out, p_read = PRICES.get(model, PRICES["claude-opus-5-5"])
    usd = (p_in * plain + p_in * Decimal("1.25") * written + p_read * read + p_out * out) / Decimal(1_000_000)
    return plain + written + read, out, usd


class _Base:
    provider = "anthropic"

    def __init__(self, settings: Settings, client: Any = None) -> None:
        if client is None:
            if settings.anthropic_api_key is None:
                raise ValueError("ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                timeout=settings.llm_timeout_s,
                max_retries=2,  # SDK retries 408/409/429/5xx and connection errors with backoff
            )
        self._client = client
        self._s = settings

    def _create(self, **kw: Any) -> Any:
        extra: dict[str, Any] = {}
        if self._s.anthropic_refusal_fallback:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            return self._client.beta.messages.create(
                model=self._s.anthropic_model,
                max_tokens=self._s.anthropic_max_tokens,
                cache_control={"type": "ephemeral"},
                **extra,
                **kw,
            )
        except anthropic.RateLimitError as e:
            raise LLMError("HTTP 429 rate_limit_exceeded") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"HTTP {e.status_code}") from e
        except anthropic.APIConnectionError as e:  # includes timeouts
            raise LLMError(f"connection: {type(e).__name__}") from e

    @staticmethod
    def _check(response: Any) -> None:
        if response.stop_reason == "refusal":
            raise LLMError("refusal")
        if response.stop_reason == "max_tokens":
            raise LLMError("max_tokens")


class AnthropicJsonClient(_Base):
    """JsonLLM on Claude: structured output constrained by `output_config.format` (json_schema)."""

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> LLMReply:
        response = self._create(
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self._s.anthropic_effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        self._check(response)
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise LLMError("no text block")
        try:
            data = json.loads(text)
        except ValueError as e:
            raise LLMError("reply is not JSON") from e
        if not isinstance(data, dict):
            raise LLMError("reply is not a JSON object")
        tin, tout, usd = cost_of(response.model, response.usage)
        return LLMReply(data=data, model=str(response.model), input_tokens=tin, output_tokens=tout, cost=usd)


def to_anthropic_tools(tools: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI-style function tools (the framework's neutral shape) → Anthropic tool definitions."""
    out = []
    for t in tools:
        fn = t["function"]
        out.append(
            {"name": fn["name"], "description": fn.get("description", ""), "input_schema": fn["parameters"]}
        )
    return out


def to_anthropic_messages(messages: Sequence[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """The framework's neutral transcript → (system, Anthropic messages). Assistant turns produced by Claude are
    replayed verbatim from `_raw`; consecutive tool results become one user message of `tool_result` blocks."""
    system = ""
    out: list[dict[str, Any]] = []

    def user_blocks() -> list[Any]:
        if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
            return out[-1]["content"]
        out.append({"role": "user", "content": []})
        return out[-1]["content"]  # type: ignore[no-any-return]

    for m in messages:
        role = m["role"]
        if role == "system":
            system = str(m["content"])
        elif role == "user":
            user_blocks().append({"type": "text", "text": str(m["content"])})
        elif role == "tool":
            content = str(m["content"])
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": content,
            }
            if content.startswith("ERROR"):
                block["is_error"] = True
            user_blocks().append(block)
        elif role == "assistant":
            if m.get("_raw") is not None:
                out.append({"role": "assistant", "content": m["_raw"]})
                continue
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for c in m.get("tool_calls") or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": c["id"],
                        "name": c["function"]["name"],
                        "input": json.loads(c["function"]["arguments"] or "{}"),
                    }
                )
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
    return system, out


class AnthropicChatClient(_Base):
    """ChatLLM on Claude: Messages API tool use."""

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> ChatTurn:
        system, msgs = to_anthropic_messages(messages)
        t0 = time.monotonic()
        response = self._create(
            system=system,
            messages=msgs,
            tools=to_anthropic_tools(tools),
            output_config={"effort": self._s.anthropic_effort},
        )
        self._check(response)
        text = (
            " ".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip() or None
        )
        calls = tuple(
            ToolCallRequest(id=str(b.id), name=str(b.name), arguments=json.dumps(b.input))
            for b in response.content
            if getattr(b, "type", None) == "tool_use"
        )
        tin, tout, usd = cost_of(response.model, response.usage)
        return ChatTurn(
            content=text,
            tool_calls=calls,
            model=str(response.model),
            input_tokens=tin,
            output_tokens=tout,
            latency_ms=int((time.monotonic() - t0) * 1000),
            finish_reason=str(response.stop_reason),
            raw=list(response.content),
            cost=usd,
        )
