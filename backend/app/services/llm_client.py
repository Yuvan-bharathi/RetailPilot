"""Groq chat-completions client for explanation text (D-44).

- Models: `llm_model` (default `openai/gpt-oss-120b`), then `llm_fallback_model` (`openai/gpt-oss-20b`) when the
  primary fails, times out or is rate-limited. Both are Groq *production* models.
- Structured output: `response_format = json_schema` with `strict: true` (constrained decoding on gpt-oss), so
  the reply is always the JSON object we ask for.
- gpt-oss are reasoning models: `reasoning_effort` low and `include_reasoning: false` keep the reasoning out of
  the response; reasoning tokens still count toward `max_completion_tokens`.
- One retry on 429 / 5xx with the server's Retry-After (capped), then the fallback model.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

#: USD per 1M tokens (input, output) from console.groq.com/docs/models, checked 2026-11-04. Used for
#: `llm_usage.est_cost` only — an estimate, never shown as a business figure.
PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "openai/gpt-oss-120b": (Decimal("0.15"), Decimal("0.60")),
    "openai/gpt-oss-20b": (Decimal("0.075"), Decimal("0.30")),
}

_RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMReply:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def est_cost(self) -> Decimal:
        price_in, price_out = PRICES_PER_MTOK.get(self.model, (Decimal(0), Decimal(0)))
        return (price_in * self.input_tokens + price_out * self.output_tokens) / Decimal(1_000_000)


class LLMError(Exception):
    """Every model failed; the caller falls back to deterministic templates."""


class JsonLLM(Protocol):
    def complete_json(self, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> LLMReply: ...


class GroqClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None, sleep: Any = time.sleep) -> None:
        if settings.groq_api_key is None:
            raise ValueError("GROQ_API_KEY is not set")
        self._key = settings.groq_api_key.get_secret_value()
        self._settings = settings
        self._http = http or httpx.Client(timeout=settings.llm_timeout_s)
        self._sleep = sleep

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> LLMReply:
        errors: list[str] = []
        for model in dict.fromkeys([self._settings.llm_model, self._settings.llm_fallback_model]):
            try:
                return self._call(model, system, user, schema_name, schema)
            except (httpx.HTTPError, LLMError, ValueError, KeyError) as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
                logger.warning("LLM call failed on %s: %s", model, type(exc).__name__)
        raise LLMError("; ".join(errors))

    def _call(self, model: str, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> LLMReply:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self._settings.llm_temperature,
            "max_completion_tokens": self._settings.llm_max_completion_tokens,
            "reasoning_effort": self._settings.llm_reasoning_effort,
            "include_reasoning": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        response = self._http.post(GROQ_CHAT_URL, json=body, headers=headers)
        if response.status_code in _RETRY_STATUS:
            wait = min(float(response.headers.get("retry-after", "1") or 1), 10.0)
            self._sleep(wait)
            response = self._http.post(GROQ_CHAT_URL, json=body, headers=headers)
        if response.status_code != 200:
            raise LLMError(f"HTTP {response.status_code}")
        payload = response.json()
        choice = payload["choices"][0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise LLMError(f"finish_reason={choice.get('finish_reason')}")  # e.g. cut off by the token limit
        data = json.loads(choice["message"]["content"])
        if not isinstance(data, dict):
            raise LLMError("reply is not a JSON object")
        usage = payload.get("usage") or {}
        return LLMReply(
            data=data,
            model=str(payload.get("model") or model),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )
