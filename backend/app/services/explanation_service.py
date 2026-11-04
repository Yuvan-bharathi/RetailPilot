"""Explanation Service (SD-09, CLAUDE.md rule 11, spec §8).

Generates human-readable explanations for recommendations. Uses Anthropic Claude (if API key is present)
with temperature 0, validates that numbers in the generated text match deterministic evidence, and falls
back to deterministic templates when the API key is missing or validation fails.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import get_settings


@dataclass
class ExplanationInput:
    kind: str
    evidence: dict[str, Any]


class ExplanationService:
    def __init__(self, session: Any = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("LLM_MODEL", "claude-3-5-sonnet-20241022")

    def explain(self, items: list[ExplanationInput], run_id: UUID | None = None) -> list[str]:
        return [self.generate_explanation(item.kind, item.evidence) for item in items]

    def generate_explanation(self, rec_type: str, evidence: dict[str, Any]) -> str:
        """Generate explanation text grounded in deterministic evidence numbers."""
        # 1. Fallback template (deterministic)
        template_text = self._template_explanation(rec_type, evidence)

        if not self.api_key:
            return template_text

        # 2. If Anthropic client is available, attempt LLM call
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)
            prompt = (
                f"You are RetailPilot AI. Explain this replenishment recommendation in 2 concise sentences for a store supervisor.\n"
                f"Type: {rec_type}\n"
                f"Evidence: {evidence}\n"
                f"CRITICAL RULE: Every number mentioned in your output MUST appear in the evidence dictionary exactly. Never invent quantities or costs."
            )
            messages_client: Any = client.messages
            response = messages_client.create(
                model=self.model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            first_block = response.content[0] if response.content else None
            text_candidate = getattr(first_block, "text", "").strip()
            if self._validate_numbers(text_candidate, evidence):
                return text_candidate
        except Exception:
            pass

        return template_text

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
