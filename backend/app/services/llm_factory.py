"""The one place that chooses the LLM provider (D-53): `LLM_PROVIDER=anthropic|groq|template`, default anthropic.

Both providers implement the same two contracts — `JsonLLM.complete_json` (explanations, reviewer judge) and
`ChatLLM.chat` (agent tool loop with a submit tool) — so agents, ExplanationService and the evals are
provider-agnostic. A provider without a key, or "template", yields None: callers use their deterministic path.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings


def make_json_llm(settings: Settings | None = None) -> Any:
    s = settings or get_settings()
    if s.llm_provider == "anthropic" and s.anthropic_api_key is not None:
        from app.services.anthropic_client import AnthropicJsonClient

        return AnthropicJsonClient(s)
    if s.llm_provider == "groq" and s.groq_api_key is not None:
        from app.services.llm_client import GroqClient

        return GroqClient(s)
    return None


def make_chat_llm(settings: Settings | None = None) -> Any:
    s = settings or get_settings()
    if s.llm_provider == "anthropic" and s.anthropic_api_key is not None:
        from app.services.anthropic_client import AnthropicChatClient

        return AnthropicChatClient(s)
    if s.llm_provider == "groq" and s.groq_api_key is not None:
        from app.agents.llm.chat import GroqChatClient

        return GroqChatClient(s)
    return None


def provider_label(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    model = {"anthropic": s.anthropic_model, "groq": s.llm_model}.get(s.llm_provider, "templates")
    return f"{s.llm_provider}:{model}"
