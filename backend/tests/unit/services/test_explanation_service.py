"""ExplanationService and GroqClient (D-44): grounding, scoping, batching, fallbacks — no network."""

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.explanation_service import (
    PRIVATE_FIELDS,
    ExplanationInput,
    ExplanationService,
    is_grounded,
    llm_facts,
    template_explanation,
)
from app.services.llm_client import GROQ_CHAT_URL, GroqClient, LLMError, LLMReply

TRANSFER_EVIDENCE = {
    "kind": "TRANSFER",
    "transfer_qty": 24,
    "po_remainder_qty": 16,
    "donor": {"store": {"store_id": str(uuid4()), "name": "Store A - Residential"}, "qty": 24},
    "donor_surplus": 24,
    "donor_protected_requirement": 30,
    "transfer_cost": "222.00",
    "po_incremental_cost": "410.50",
}


def settings(**kw: Any) -> Settings:
    """Defaults from the code only — never the developer's .env (which may pin another model or a real key)."""
    base: dict[str, Any] = {"groq_api_key": SecretStr("test-key"), "llm_batch_size": 2}
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


class FakeLLM:
    """Returns canned texts by item id and records each batch."""

    def __init__(self, texts: dict[int, str], fail: bool = False) -> None:
        self.texts, self.fail, self.batches = texts, fail, []

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> LLMReply:
        items = json.loads(user)["items"]
        self.batches.append(items)
        if self.fail:
            raise LLMError("down")
        data = {
            "explanations": [
                {"id": i["id"], "text": self.texts[i["id"]]} for i in items if i["id"] in self.texts
            ]
        }
        return LLMReply(data=data, model="openai/gpt-oss-120b", input_tokens=1000, output_tokens=200)


# --- grounding and scoping -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Move 24 units from Store A; it costs ₹222.00 versus ₹410.50 for a PO.", True),
        ("Move 24 units now and order the other 16.", True),
        ("The transfer costs ₹222 instead of ₹410.5.", True),  # 222 = 222.00, 410.5 = 410.50
        ("Move 25 units.", False),  # not in the facts
        ("Saves ₹188.50 versus a purchase order.", False),  # a computed number is not a fact
        ("Store A keeps 30 units of its requirement.", False),  # 30 is donor stock: private, not a fact
    ],
)
def test_text_is_grounded_only_in_the_shared_facts(text: str, ok: bool) -> None:
    assert is_grounded(text, llm_facts(TRANSFER_EVIDENCE)) is ok


def test_facts_drop_private_donor_stock_ids_and_nulls() -> None:
    facts = llm_facts(TRANSFER_EVIDENCE | {"supplier_id": str(uuid4()), "lost_revenue": None})
    flat = json.dumps(facts)
    assert not PRIVATE_FIELDS & set(facts)
    assert "store_id" not in flat and "supplier_id" not in flat and "lost_revenue" not in flat
    assert facts["donor"] == {"store": {"name": "Store A - Residential"}, "qty": 24}


def test_numbers_inside_fact_strings_and_thousands_separators_count() -> None:
    facts = {"product": {"name": "Rice 5 kg"}, "total_value": "125000.00"}
    assert is_grounded("Rice 5 kg order worth ₹1,25,000 is waiting.", facts)  # Indian lakh grouping
    assert is_grounded("Rice 5 kg order worth ₹125,000.00 is waiting.", facts)
    assert not is_grounded("Rice 6 kg order worth ₹125,000 is waiting.", facts)


# --- templates -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "evidence"),
    [
        ("TRANSFER", TRANSFER_EVIDENCE),
        ("TRANSFER", {"from_store_name": "Store B", "qty": 20, "transfer_cost": 150.0}),
        ("REORDER", {"own_requirement": 40, "available": 0, "need_qty": 16}),
        ("REORDER", {}),
        ("CO_REPLENISH", {"linked_product": {"name": "Bread"}, "lift": 1.8, "qty": 3}),
        ("EXPIRY_ALERT", {"at_risk": 30, "days_left": 5}),
        ("PURCHASE_ORDER", {"line_count": 3, "total_value": "51234.50"}),
        ("ASSORTMENT_GAP", {"lift": 2.0}),
        ("NEEDS_REVIEW", {"reason": "LOW_CONFIDENCE"}),
        ("SOMETHING_NEW", {"qty": 1}),
    ],
)
def test_templates_state_only_facts_and_never_private_stock(kind: str, evidence: dict[str, Any]) -> None:
    text = template_explanation(kind, evidence)
    assert text and len(text) <= 400
    assert is_grounded(text, llm_facts(evidence))
    assert "30" not in text or kind == "EXPIRY_ALERT"  # donor_protected_requirement never leaks
    assert " 0 units" not in text or evidence.get("available") == 0


def test_missing_facts_do_not_become_zero() -> None:
    assert template_explanation("REORDER", {}) == (
        "Stock is below this store's requirement, so a purchase order is proposed."
    )


# --- service -------------------------------------------------------------------------------------------------------


def test_batches_accepts_grounded_text_and_falls_back_per_item() -> None:
    items = [
        ExplanationInput("TRANSFER", TRANSFER_EVIDENCE),
        ExplanationInput("REORDER", {"own_requirement": 40, "available": 0, "need_qty": 16}),
        ExplanationInput("EXPIRY_ALERT", {"at_risk": 30, "days_left": 5}),
    ]
    llm = FakeLLM(
        {
            0: "Move 24 units from Store A - Residential and order the other 16.",
            1: "Order 99 units now.",  # ungrounded → template
            2: "30 units expire in 5 days; move them first.",
        }
    )
    usage: list[tuple[Any, LLMReply]] = []
    service = ExplanationService(
        client=llm, settings=settings(), usage_logger=lambda r, reply: usage.append((r, reply))
    )
    run = uuid4()

    texts = service.explain(items, run_id=run)

    assert [len(b) for b in llm.batches] == [2, 1]  # llm_batch_size = 2
    assert texts[0].startswith("Move 24 units")
    assert texts[1] == template_explanation("REORDER", items[1].evidence)
    assert texts[2] == "30 units expire in 5 days; move them first."
    assert len(usage) == 2 and usage[0][0] == run
    assert usage[0][1].est_cost == Decimal("0.00027")  # 1000 × 0.15 + 200 × 0.60 per 1M tokens
    assert "donor_surplus" not in json.dumps(llm.batches)  # private fields never leave the service


def test_llm_failure_or_no_key_means_templates() -> None:
    items = [ExplanationInput("EXPIRY_ALERT", {"at_risk": 30, "days_left": 5})]
    failing = ExplanationService(client=FakeLLM({}, fail=True), settings=settings())
    assert failing.explain(items) == [template_explanation("EXPIRY_ALERT", items[0].evidence)]
    no_key = ExplanationService(settings=settings(groq_api_key=None))
    assert no_key.client is None and no_key.explain(items) == failing.explain(items)
    template_only = ExplanationService(settings=settings(llm_provider="template"))
    assert template_only.client is None


# --- Groq client ---------------------------------------------------------------------------------------------------


def _reply(content: dict[str, Any], model: str, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        },
    )


def test_groq_request_uses_strict_json_schema_and_no_reasoning_text() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == GROQ_CHAT_URL
        assert request.headers["authorization"] == "Bearer test-key"
        seen.append(json.loads(request.content))
        return _reply({"explanations": []}, "openai/gpt-oss-120b")

    client = GroqClient(settings(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    reply = client.complete_json("sys", "user", "explanations", {"type": "object"})

    body = seen[0]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert (body["reasoning_effort"], body["include_reasoning"], body["temperature"]) == ("low", False, 0.0)
    assert reply.data == {"explanations": []} and (reply.input_tokens, reply.output_tokens) == (50, 10)


def test_groq_retries_once_then_falls_back_to_the_20b_model() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "openai/gpt-oss-120b":
            return httpx.Response(429, headers={"retry-after": "2"})
        return _reply({"ok": True}, model)

    waits: list[float] = []
    client = GroqClient(
        settings(), http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=waits.append
    )
    reply = client.complete_json("s", "u", "x", {})
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert waits == [2.0] and reply.model == "openai/gpt-oss-20b"


def test_groq_truncated_answer_is_an_error_not_a_partial_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _reply({"x": 1}, json.loads(request.content)["model"], finish="length")

    client = GroqClient(settings(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError, match="finish_reason=length"):
        client.complete_json("s", "u", "x", {})


def test_client_requires_a_key() -> None:
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqClient(settings(groq_api_key=None))


def test_text_that_echoes_a_field_name_is_rejected() -> None:
    items = [ExplanationInput("REORDER", {"own_requirement": 40, "available": 0, "need_qty": 16})]
    llm = FakeLLM({0: "Reorder 16 units because need_qty is 16."})
    text = ExplanationService(client=llm, settings=settings()).explain(items)[0]
    assert text == template_explanation("REORDER", items[0].evidence)
    sent = llm.batches[0][0]
    assert "need qty" in sent["facts"] and "need_qty" not in sent["facts"]
    assert sent["type"] == "REORDER"


def test_enum_values_are_sent_as_words() -> None:
    llm = FakeLLM({})
    ExplanationService(client=llm, settings=settings()).explain(
        [ExplanationInput("REORDER", {"reason": "NO_SURPLUS_IN_ANY_STORE"})]
    )
    assert llm.batches[0][0]["facts"] == {"reason": "no surplus in any store"}
