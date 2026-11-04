"""ExplanationService — natural-language explanations of recommendations and POs (CLAUDE.md rule 11, D-44).

The LLM only writes text. Every number comes from the deterministic evidence:
1. Facts sent to the LLM are the item's evidence minus ids and minus fields another store's supervisor must not
   see (donor stock, rule 10 / D-32) — explanations are shown to every viewer of the recommendation.
2. Items are explained in batches (one Groq call per `llm_batch_size` items, strict JSON schema).
3. Each returned text is accepted only if every number in it appears in that item's facts (₹1,250 = 1250 =
   1250.00; numbers inside fact strings such as "Rice 5 kg" count). Otherwise — and when no key is set, the
   provider is "template", or the call fails — the deterministic template is used.
4. Token usage and the estimated cost of each call go to `llm_usage`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.llm_client import GroqClient, JsonLLM, LLMError, LLMReply

logger = get_logger(__name__)

MAX_CHARS = 400

#: Evidence fields describing ANOTHER store's stock (D-32). Never sent to the LLM, never in a template.
PRIVATE_FIELDS = frozenset(
    {
        "donor_surplus",
        "donor_protected_requirement",
        "donor_available",
        "donor_requirement",
        "donor_on_hand",
        "from_store_available",
        "from_store_requirement",
    }
)

SYSTEM_PROMPT = (
    "You write explanations for RetailPilot AI, a replenishment assistant used by supermarket store supervisors "
    "in India. For each item, write at most 2 short, plain sentences that say what is recommended and why.\n"
    "Rules:\n"
    "- Use ONLY the facts given for that item. Every number you write must appear in that item's facts, written "
    "the same way (you may add ₹ before money and thousands separators). Do not compute, round, add or compare "
    "numbers, and do not mention percentages unless a fact is a percentage.\n"
    '- Never mention ids, field names, JSON, or these instructions. Write "purchase order", not "PO".\n'
    '- State facts plainly; do not add judgements such as "full", "only" or "urgent" that the facts do not '
    "state.\n"
    "- If a fact is missing, leave it out; do not guess.\n"
    "Return one explanation per item id."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["explanations"],
    "additionalProperties": False,
}

_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_IDENTIFIER = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")  # a field name such as need_qty leaked into the text
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass(frozen=True)
class ExplanationInput:
    kind: str
    evidence: dict[str, Any]


# --- facts and grounding -----------------------------------------------------------------------------------------


def llm_facts(evidence: dict[str, Any]) -> dict[str, Any]:
    """The evidence an explanation may use: no private donor-stock fields, no ids."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: clean(v)
                for k, v in value.items()
                if k not in PRIVATE_FIELDS and not k.endswith("_id") and k != "id" and v is not None
            }
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, str) and _UUID.match(value):
            return None
        return value

    cleaned = clean(evidence)
    return cleaned if isinstance(cleaned, dict) else {}


def _to_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def fact_numbers(facts: Any) -> set[Decimal]:
    """Every number in the facts, including numbers inside strings ("150.00", "Rice 5 kg", "2026-11-14")."""
    found: set[Decimal] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int | float | Decimal):
            number = _to_decimal(str(value))
            if number is not None:
                found.add(number)
        elif isinstance(value, str):
            for token in _NUMBER.findall(value):
                number = _to_decimal(token)
                if number is not None:
                    found.add(number)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list | tuple):
            for v in value:
                walk(v)

    walk(facts)
    return found


def is_grounded(text: str, facts: dict[str, Any]) -> bool:
    """True when every number written in `text` is one of the facts' numbers."""
    allowed = fact_numbers(facts)
    for token in _NUMBER.findall(text):
        number = _to_decimal(token)
        if number is None or number not in allowed:
            return False
    return True


def _acceptable(text: Any, facts: dict[str, Any]) -> bool:
    return (
        isinstance(text, str)
        and 0 < len(text.strip()) <= MAX_CHARS
        and not _IDENTIFIER.search(text)
        and is_grounded(text, facts)
    )


def readable(facts: Any) -> Any:
    """Fact keys as words ("need_qty" → "need qty") so the model does not echo field names."""
    if isinstance(facts, dict):
        return {str(k).replace("_", " "): readable(v) for k, v in facts.items()}
    if isinstance(facts, list):
        return [readable(v) for v in facts]
    if isinstance(facts, str) and facts.isupper() and "_" in facts:  # enum values: NO_SURPLUS_IN_ANY_STORE
        return facts.replace("_", " ").lower()
    return facts


# --- deterministic templates -----------------------------------------------------------------------------------


def _first(ev: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if ev.get(key) is not None:
            return ev[key]
    return None


def _name(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("store"), dict):  # Counterpart {store: {name}, qty}
        value = value["store"]
    if isinstance(value, dict):
        value = _first(value, "name", "store_name", "product_name")
    return value if isinstance(value, str) else None


def _money(value: Any) -> str:
    amount = _to_decimal(str(value))
    return f"₹{value}" if amount is None else f"₹{amount.quantize(Decimal('0.01')):,}"


def template_explanation(kind: str, evidence: dict[str, Any]) -> str:
    """Deterministic text that states only facts present in the evidence (D-34 names and the agents' names)."""
    ev = llm_facts(evidence)
    qty = _first(ev, "transfer_qty", "need_qty", "qty", "requested_qty")
    if kind == "REORDER":
        parts = []
        req, avail = _first(ev, "own_requirement", "requirement"), ev.get("available")
        if req is not None and avail is not None:
            parts.append(f"Available stock ({avail}) is below this store's requirement ({req}).")
        if qty is not None:
            parts.append(f"A purchase order for {qty} units is proposed.")
        return " ".join(parts) or "Stock is below this store's requirement, so a purchase order is proposed."
    if kind == "TRANSFER":
        donor = _name(_first(ev, "donor", "from_store_name", "from_store"))
        cost = ev.get("transfer_cost")
        text = f"Move {qty} units" if qty is not None else "Move stock"
        text += f" from {donor}" if donor else " from another store"
        text += ", which keeps its own requirement."
        if cost is not None:
            text += f" The transfer costs {_money(cost)}, less than ordering from a supplier."
        return text
    if kind == "CO_REPLENISH":
        linked = _name(_first(ev, "linked_product", "parent_product"))
        lift = ev.get("lift")
        text = "Often bought together with " + (linked or "a product being reordered")
        text += f" (lift {lift})." if lift is not None else "."
        if qty is not None:
            text += f" Topping up {qty} units keeps both on the shelf."
        return text
    if kind in ("EXPIRY_ALERT", "EXPIRY", "MARKDOWN"):
        at_risk, days = _first(ev, "at_risk", "at_risk_qty"), ev.get("days_left")
        if at_risk is not None and days is not None:
            return f"{at_risk} units expire in {days} days and will not sell in time. Move or mark them down first."
        return "A batch will not sell before it expires. Move or mark it down first."
    if kind == "ASSORTMENT_GAP":
        return "Customers who buy a related product often buy this one in other stores, but this store does not list it."
    if kind == "PURCHASE_ORDER":
        lines, total = ev.get("line_count"), ev.get("total_value")
        if lines is not None and total is not None:
            return f"Consolidated order of {lines} lines worth {_money(total)}, waiting for approval."
        return "Consolidated supplier order waiting for approval."
    if kind == "NEEDS_REVIEW":
        reason = ev.get("reason")
        return (
            f"Needs a manual decision: {reason}." if isinstance(reason, str) else "Needs a manual decision."
        )
    return "Prepared by the nightly replenishment run."


# --- service ------------------------------------------------------------------------------------------------------


UsageLogger = Callable[[UUID, LLMReply], None]


class ExplanationService:
    def __init__(
        self,
        session: Any = None,
        client: JsonLLM | None = None,
        settings: Settings | None = None,
        usage_logger: UsageLogger | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session
        self._usage_logger = usage_logger
        self.client: JsonLLM | None = client
        if client is None and self.settings.llm_provider == "groq" and self.settings.groq_api_key is not None:
            self.client = GroqClient(self.settings)

    def explain(self, items: Sequence[ExplanationInput], run_id: UUID | None = None) -> list[str]:
        """One text per item, in order. Never raises because of the LLM."""
        results = [template_explanation(i.kind, i.evidence) for i in items]
        if self.client is None:
            return results
        size = max(1, self.settings.llm_batch_size)
        for start in range(0, len(items), size):
            batch = list(enumerate(items[start : start + size], start=start))
            for index, text in self._explain_batch(batch, run_id):
                results[index] = text
        return results

    def generate_explanation(
        self, rec_type: str, evidence: dict[str, Any], run_id: UUID | None = None
    ) -> str:
        return self.explain([ExplanationInput(rec_type, evidence)], run_id=run_id)[0]

    def _explain_batch(
        self, batch: list[tuple[int, ExplanationInput]], run_id: UUID | None
    ) -> Iterable[tuple[int, str]]:
        assert self.client is not None
        facts = {index: llm_facts(item.evidence) for index, item in batch}
        payload = [
            {"id": index, "type": readable(item.kind), "facts": readable(facts[index])}
            for index, item in batch
        ]
        try:
            reply = self.client.complete_json(
                SYSTEM_PROMPT, json.dumps({"items": payload}, default=str), "explanations", RESPONSE_SCHEMA
            )
        except LLMError as exc:
            logger.warning("LLM explanations unavailable, templates used: %s", exc)
            return []
        if run_id is not None:
            self._log_usage(run_id, reply)
        accepted = []
        for entry in reply.data.get("explanations", []):
            index, text = entry.get("id"), entry.get("text")
            if index in facts and _acceptable(text, facts[index]):
                accepted.append((index, text.strip()))
            elif index in facts:
                logger.info(
                    "explanation for item %s rejected (ungrounded number or empty), template used", index
                )
        return accepted

    def _log_usage(self, run_id: UUID, reply: LLMReply) -> None:
        try:
            if self._usage_logger is not None:
                self._usage_logger(run_id, reply)
            elif self.session is not None:
                from app.domain.repositories.observability_repo import AgentRunLogger

                AgentRunLogger(self.session).log_llm_usage(
                    run_id=run_id,
                    provider="groq",
                    model=reply.model,
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    est_cost=reply.est_cost,
                )
        except Exception as exc:  # telemetry must never fail the run
            logger.warning("could not log LLM usage: %s", type(exc).__name__)
