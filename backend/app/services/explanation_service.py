"""Explanation Service (SD-09, CLAUDE.md rule 11, spec §8).

Generates human-readable explanations for recommendations. Uses Groq or Anthropic LLM
with temperature 0, validates that numbers in the generated text match deterministic evidence,
logs token telemetry to LLMUsage, and falls back to deterministic templates when the API key
is missing or validation fails.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ExplanationInput:
    kind: str
    evidence: dict[str, Any]


class ExplanationService:
    def __init__(self, session: Any = None) -> None:
        self.session = session
        self.settings = get_settings()

        # Groq key takes priority if present, otherwise Anthropic
        self.groq_api_key = (
            self.settings.groq_api_key.get_secret_value()
            if self.settings.groq_api_key
            else os.environ.get("GROQ_API_KEY")
        )
        self.anthropic_api_key = (
            self.settings.anthropic_api_key.get_secret_value()
            if self.settings.anthropic_api_key
            else os.environ.get("ANTHROPIC_API_KEY")
        )

        self.provider = os.environ.get("LLM_PROVIDER", self.settings.llm_provider)
        self.model = os.environ.get("LLM_MODEL", self.settings.llm_model)

    def explain(self, items: list[ExplanationInput], run_id: UUID | None = None) -> list[str]:
        return [self.generate_explanation(item.kind, item.evidence, run_id=run_id) for item in items]

    def generate_explanation(
        self, rec_type: str, evidence: dict[str, Any], run_id: UUID | None = None
    ) -> str:
        """Generate explanation text grounded in deterministic evidence numbers."""
        # Fallback template (deterministic)
        template_text = self._template_explanation(rec_type, evidence)

        # 1. Groq High-Speed LLM Call
        if self.groq_api_key and (self.provider == "groq" or not self.anthropic_api_key):
            try:
                candidate = self._call_groq(rec_type, evidence, run_id=run_id)
                if candidate and self._validate_numbers(candidate, evidence):
                    return candidate
            except Exception as e:
                logger.warning(f"Groq explanation failed, using fallback template: {e}")

        # 2. Anthropic LLM Call (if configured)
        elif self.anthropic_api_key and self.provider == "anthropic":
            try:
                candidate = self._call_anthropic(rec_type, evidence, run_id=run_id)
                if candidate and self._validate_numbers(candidate, evidence):
                    return candidate
            except Exception as e:
                logger.warning(f"Anthropic explanation failed, using fallback template: {e}")

        return template_text

    def _call_groq(
        self, rec_type: str, evidence: dict[str, Any], run_id: UUID | None = None
    ) -> str | None:
        """Call Groq chat completion API with temperature 0."""
        prompt = (
            "You are RetailPilot AI, an autonomous replenishment engine for retail stores.\n"
            "Explain this replenishment recommendation in 2 concise sentences for a store supervisor.\n"
            f"Type: {rec_type}\n"
            f"Evidence: {evidence}\n"
            "CRITICAL RULE: Every number mentioned in your output MUST appear in the evidence dictionary exactly. "
            "Never invent quantities, dates, or costs. If you mention a number, use the exact value from evidence."
        )

        with httpx.Client(timeout=10.0) as client:
            res = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 150,
                },
            )

        if res.status_code == 200:
            data = res.json()
            text_candidate = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})

            # Telemetry logging to LLMUsage in DB
            if run_id and self.session:
                try:
                    from app.domain.repositories.observability_repo import AgentRunLogger

                    AgentRunLogger(self.session).log_llm_usage(
                        run_id=run_id,
                        provider="groq",
                        model=self.model,
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                    )
                except Exception as log_err:
                    logger.debug(f"Failed to log LLM usage telemetry: {log_err}")

            return str(text_candidate)
        else:
            logger.warning(f"Groq API returned error {res.status_code}: {res.text}")
            return None

    def _call_anthropic(
        self, rec_type: str, evidence: dict[str, Any], run_id: UUID | None = None
    ) -> str | None:
        """Call Anthropic messages API."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        prompt = (
            "You are RetailPilot AI. Explain this replenishment recommendation in 2 concise sentences for a store supervisor.\n"
            f"Type: {rec_type}\n"
            f"Evidence: {evidence}\n"
            "CRITICAL RULE: Every number mentioned in your output MUST appear in the evidence dictionary exactly. Never invent quantities or costs."
        )
        messages_client: Any = client.messages
        response = messages_client.create(
            model=self.model,
            max_tokens=150,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        first_block = response.content[0] if response.content else None
        text_val = getattr(first_block, "text", "")
        return str(text_val).strip() if text_val else None

    def _validate_numbers(self, text: str, evidence: dict[str, Any]) -> bool:
        """Validates that all numbers mentioned in text exist within evidence values."""
        numbers_in_text = set(re.findall(r"\b\d+(?:\.\d+)?\b", text))
        evidence_values = set()

        def _extract(val: Any) -> None:
            if isinstance(val, (int, float)):
                evidence_values.add(str(val))
                if isinstance(val, float) and val.is_integer():
                    evidence_values.add(str(int(val)))
            elif isinstance(val, dict):
                for v in val.values():
                    _extract(v)
            elif isinstance(val, list):
                for v in val:
                    _extract(v)

        _extract(evidence)
        # Check that numeric tokens are grounded
        return numbers_in_text.issubset(evidence_values)

    def _template_explanation(self, rec_type: str, ev: dict[str, Any]) -> str:
        """Deterministic fallback explanation templates."""
        if rec_type == "REORDER":
            req = ev.get("requirement", ev.get("own_requirement", 0))
            avail = ev.get("available", 0)
            return (
                f"Stock position ({avail} units) has fallen below store requirement ({req} units). "
                f"Reorder is proposed to restore safe cover."
            )
        if rec_type == "TRANSFER":
            qty = ev.get("qty", ev.get("transfer_qty", 0))
            donor = ev.get("donor_name", ev.get("from_store_name", "sibling store"))
            return (
                f"Transfer of {qty} units proposed from {donor} where genuine surplus exists. "
                f"Peer transfer is lower cost than placing a new supplier order."
            )
        if rec_type == "CO_REPLENISH":
            parent = ev.get("parent_product", "main product")
            lift = ev.get("lift", 1.0)
            return (
                f"Frequently purchased together with {parent} (lift: {lift:.1f}). "
                f"Restocking complement avoids assortment gaps."
            )
        if rec_type == "EXPIRY_ALERT":
            days = ev.get("days_left", 0)
            risk = ev.get("at_risk", 0)
            return (
                f"Batch has {risk} units at risk of expiring in {days} days. "
                f"Accelerated transfer or priority display recommended."
            )
        if rec_type == "ASSORTMENT_GAP":
            return (
                "Product has high customer affinity in peer stores but is unlisted or missing. "
                "Adding to store assortment is recommended."
            )
        return "Replenishment recommendation prepared by nightly automated run."
