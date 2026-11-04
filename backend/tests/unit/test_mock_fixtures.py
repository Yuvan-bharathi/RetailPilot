"""The frontend mock fixtures match the API contract and are regenerable (D-32, Phase 8a)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from app.api.routers.business_rules import BusinessRuleDTO
from app.domain.schemas.dtos import (
    AnalyticsDTO,
    BatchDTO,
    DashboardInsights,
    DashboardSummary,
    Evidence,
    InventoryMovementDTO,
    InventoryRowDTO,
    PurchaseOrderDTO,
    RecommendationDTO,
    RunInfoDTO,
    StoreDTO,
    TransferOrderDTO,
)
from scripts.export_mock_fixtures import DEFAULT_OUT, main

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def fixtures() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))
    return data


def test_every_section_validates_against_the_dtos(fixtures: dict[str, Any]) -> None:
    TypeAdapter(list[StoreDTO]).validate_python(fixtures["stores"])
    RunInfoDTO.model_validate(fixtures["latest_run"])
    TypeAdapter(list[RecommendationDTO]).validate_python(fixtures["recommendations"])
    TypeAdapter(dict[str, Evidence]).validate_python(fixtures["evidence"])
    TypeAdapter(list[TransferOrderDTO]).validate_python(fixtures["transfers"])
    TypeAdapter(list[PurchaseOrderDTO]).validate_python(fixtures["purchase_orders"])
    TypeAdapter(dict[str, DashboardSummary]).validate_python(fixtures["dashboard"])
    TypeAdapter(dict[str, DashboardInsights]).validate_python(fixtures["dashboard_insights"])
    TypeAdapter(dict[str, AnalyticsDTO]).validate_python(fixtures["analytics"])
    TypeAdapter(list[BusinessRuleDTO]).validate_python(fixtures["business_rules"])
    for section, model in (
        ("inventory", InventoryRowDTO),
        ("movements", InventoryMovementDTO),
        ("batches", BatchDTO),
    ):
        TypeAdapter(dict[str, list[model]]).validate_python(fixtures[section])  # type: ignore[valid-type]


def test_every_recommendation_has_evidence_of_its_kind(fixtures: dict[str, Any]) -> None:
    kinds = {
        "TRANSFER": "TRANSFER",
        "REORDER": "REORDER",
        "CO_REPLENISH": "CO_REPLENISH",
        "EXPIRY_ALERT": "EXPIRY",
    }
    for rec in fixtures["recommendations"]:
        evidence = fixtures["evidence"][rec["rec_id"]]
        expected = "NEEDS_REVIEW" if rec["status"] == "NEEDS_REVIEW" else kinds[rec["rec_type"]]
        assert evidence["kind"] == expected, rec["rec_id"]


def test_the_five_scenarios_are_indexed(fixtures: dict[str, Any]) -> None:
    recs = {r["rec_id"]: r for r in fixtures["recommendations"]}
    scenarios = fixtures["scenarios"]

    assert sorted(scenarios) == ["1", "2", "3", "4", "5"]
    three = sorted((recs[i]["rec_type"], recs[i]["qty"]) for i in scenarios["3"]["rec_ids"])
    assert three == [("REORDER", 16), ("TRANSFER", 24)]
    assert all(recs[i]["rec_id"] for s in scenarios.values() for i in s["rec_ids"])


def test_fixtures_are_regenerable_and_up_to_date(tmp_path: Path) -> None:
    out = tmp_path / "fixtures.json"

    assert main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == DEFAULT_OUT.read_text(encoding="utf-8"), (
        "frontend/src/mocks/data/fixtures.json is stale — run: uv run python -m scripts.export_mock_fixtures"
    )
