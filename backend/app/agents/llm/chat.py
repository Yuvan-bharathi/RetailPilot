"""Chat client with tool calling for the Objective III agents (docs/08, D-50).

- `GroqChatClient`: Groq chat completions (OpenAI-compatible `tools` / `tool_calls`; same provider, models, retry
  and fallback as the explanation client, D-44). The final structured answer is a "submit_*" function call, so
  the output is validated with Pydantic like any tool argument.
- `ScriptedChatLLM`: replays recorded turns — the evaluation harness and CI run without a live model (docs/08 §7).
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.llm_client import GROQ_CHAT_URL, PRICES_PER_MTOK, LLMError

logger = get_logger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: str  # raw JSON text from the model


@dataclass(frozen=True)
class ChatTurn:
    content: str | None
    tool_calls: tuple[ToolCallRequest, ...]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    finish_reason: str | None = None

    @property
    def est_cost(self) -> Decimal:
        price_in, price_out = PRICES_PER_MTOK.get(self.model, (Decimal(0), Decimal(0)))
        return (price_in * self.input_tokens + price_out * self.output_tokens) / Decimal(1_000_000)


class ChatLLM(Protocol):
    provider: str

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> ChatTurn: ...


class GroqChatClient:
    provider = "groq"

    def __init__(self, settings: Settings, http: httpx.Client | None = None, sleep: Any = time.sleep) -> None:
        if settings.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is not set")
        self._key = settings.groq_api_key.get_secret_value()
        self._settings = settings
        self._http = http or httpx.Client(timeout=settings.llm_timeout_s)
        self._sleep = sleep

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> ChatTurn:
        errors: list[str] = []
        for model in dict.fromkeys([self._settings.llm_model, self._settings.llm_fallback_model]):
            try:
                return self._call(model, messages, tools)
            except (httpx.HTTPError, LLMError, ValueError, KeyError) as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
                logger.warning("agent LLM call failed on %s: %s", model, str(exc)[:160])
        raise LLMError("; ".join(errors))

    def _call(
        self, model: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ChatTurn:
        body: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": self._settings.llm_temperature,
            "max_completion_tokens": self._settings.llm_max_completion_tokens,
            "reasoning_effort": self._settings.llm_reasoning_effort,
            "include_reasoning": False,
        }
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self._key}"}
        t0 = time.monotonic()
        response = self._http.post(GROQ_CHAT_URL, json=body, headers=headers)
        if response.status_code in _RETRY_STATUS:
            self._sleep(min(float(response.headers.get("retry-after", "1") or 1), 10.0))
            response = self._http.post(GROQ_CHAT_URL, json=body, headers=headers)
        if response.status_code == 400 and "tool_use_failed" in response.text:
            # gpt-oss on Groq occasionally emits a malformed tool call (400 tool_use_failed): one retry
            response = self._http.post(GROQ_CHAT_URL, json=body, headers=headers)
        if response.status_code != 200:
            code = ""
            with contextlib.suppress(ValueError):
                code = str(response.json().get("error", {}).get("code") or "")
            raise LLMError(f"HTTP {response.status_code} {code}".strip())
        payload = response.json()
        choice = payload["choices"][0]
        message = choice["message"]
        calls = tuple(
            ToolCallRequest(
                id=str(c["id"]), name=str(c["function"]["name"]), arguments=c["function"]["arguments"] or "{}"
            )
            for c in (message.get("tool_calls") or [])
        )
        usage = payload.get("usage") or {}
        return ChatTurn(
            content=message.get("content"),
            tool_calls=calls,
            model=str(payload.get("model") or model),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=int((time.monotonic() - t0) * 1000),
            finish_reason=choice.get("finish_reason"),
        )


@dataclass
class ScriptedChatLLM:
    """Replays recorded model turns. Each turn is either {"tool_calls": [{"name", "arguments"}]} or
    {"content": "..."}; a callable turn receives the messages so far (e.g. to echo an id a tool returned).
    `raise_on` makes a turn fail like a provider error (tool-failure / model-error eval cases)."""

    turns: list[dict[str, Any] | Callable[[Sequence[dict[str, Any]]], dict[str, Any]]]
    model: str = "recorded/gpt-oss-120b"
    tokens_per_turn: tuple[int, int] = (900, 120)
    latency_ms: int = 0
    raise_on: set[int] = field(default_factory=set)
    provider: str = "recorded"
    calls: int = 0

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> ChatTurn:
        index = self.calls
        self.calls += 1
        if index in self.raise_on:
            raise LLMError("recorded provider error")
        if index >= len(self.turns):
            return ChatTurn("", (), self.model, *self.tokens_per_turn, self.latency_ms, "stop")
        turn = self.turns[index]
        data = turn(messages) if callable(turn) else turn
        calls = tuple(
            ToolCallRequest(
                id=f"call_{index}_{i}",
                name=c["name"],
                arguments=c["arguments"] if isinstance(c["arguments"], str) else json.dumps(c["arguments"]),
            )
            for i, c in enumerate(data.get("tool_calls", []))
        )
        return ChatTurn(
            data.get("content"), calls, self.model, *self.tokens_per_turn, self.latency_ms, "stop"
        )


@dataclass
class RoutedChatLLM:
    """Routes each conversation to the scripted model of the agent whose system prompt contains the marker
    (several LLM agents share one injected client in a pipeline run). Unrouted agents get a reply without a tool
    call, so they end with `no_submit` and use their deterministic baseline."""

    routes: dict[str, ScriptedChatLLM]
    provider: str = "recorded"

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> ChatTurn:
        system = str(messages[0].get("content", "")) if messages else ""
        for marker, llm in self.routes.items():
            if marker in system:
                return llm.chat(messages, tools)
        return ChatTurn("", (), "recorded/none", 0, 0, 0, "stop")
