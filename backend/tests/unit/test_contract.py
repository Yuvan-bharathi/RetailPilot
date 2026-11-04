"""API contract (D-32): stubs answer 501 with the standard body; DTOs enforce store scoping; the frontend's copy
of the OpenAPI spec is up to date."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain.schemas.common import Counterpart, PageParams, StoreRef
from app.domain.schemas.dtos import RecommendationDTO, TransferEvidenceDTO
from app.main import create_app

FRONTEND_OPENAPI = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"
ANY_ID = "00000000-0000-0000-0000-000000000001"

STUBS = [
    ("post", "/api/v1/auth/login", {"username": "admin", "password": "x"}),
    ("get", "/api/v1/me", None),
    ("get", "/api/v1/stores", None),
    ("get", "/api/v1/runs/latest", None),
    ("get", "/api/v1/dashboard?period=LAST_7_DAYS", None),
    ("get", "/api/v1/recommendations?page=2&page_size=10&sort=-priority&type=TRANSFER", None),
    ("get", f"/api/v1/recommendations/{ANY_ID}", None),
    ("get", f"/api/v1/stores/{ANY_ID}/inventory?risk=HIGH", None),
    ("get", "/api/v1/transfers?status=PROPOSED", None),
    ("get", f"/api/v1/transfers/{ANY_ID}", None),
    ("get", "/api/v1/purchase-orders", None),
    ("get", f"/api/v1/purchase-orders/{ANY_ID}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), STUBS)
def test_contract_stubs_answer_501(client: TestClient, method: str, path: str, body: object) -> None:
    response = client.request(method, path, json=body)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("query", ["page=0", "page_size=500", "sort=drop table", "type=UNKNOWN", "page=x"])
def test_paging_parameters_are_validated(client: TestClient, query: str) -> None:
    response = client.get(f"/api/v1/recommendations?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION"


def test_page_params_defaults() -> None:
    assert PageParams() == PageParams(page=1, page_size=25, sort=None, q=None)


def test_operation_ids_are_handler_names() -> None:
    spec = create_app().openapi()

    assert spec["paths"]["/api/v1/recommendations"]["get"]["operationId"] == "list_recommendations"
    assert "Page_RecommendationDTO_" in spec["components"]["schemas"]
    money = spec["components"]["schemas"]["DashboardSummary"]["properties"]["revenue"]
    assert money["type"] == "string"


def test_counterpart_exposes_only_store_name_and_quantity() -> None:
    # CLAUDE.md rule 10: another store appears to a supervisor only as name + quantity
    assert set(Counterpart.model_fields) == {"store", "qty"}
    assert set(StoreRef.model_fields) == {"store_id", "name"}
    with pytest.raises(ValidationError):
        Counterpart.model_validate({"store": {"store_id": ANY_ID, "name": "B"}, "qty": 5, "available": 99})


def test_donor_stock_fields_are_optional_so_supervisor_views_can_omit_them() -> None:
    evidence = TransferEvidenceDTO(
        destination_shortage=40,
        donor=Counterpart(store=StoreRef(store_id=UUID(ANY_ID), name="Store A"), qty=24),
        transfer_qty=24,
        po_remainder_qty=16,
        transfer_cost=None,
        po_incremental_cost=None,
        expected_delivery=None,
        days_of_cover_before=0,
        days_of_cover_after=6,
    )

    assert evidence.donor_surplus is None and evidence.donor_protected_requirement is None
    assert evidence.donor_keeps_requirement is True  # numberless assurance for the destination supervisor
    assert "counterpart" in RecommendationDTO.model_fields


def test_money_serialises_as_two_decimal_string() -> None:
    from decimal import Decimal

    from app.domain.schemas.common import ProductRef
    from app.domain.schemas.dtos import MoverDTO

    mover = MoverDTO(
        product=ProductRef(product_id=UUID(ANY_ID), sku="S", name="N", category="c"),
        units=3,
        revenue=Decimal("1234.5"),
    )

    assert json.loads(mover.model_dump_json())["revenue"] == "1234.50"


def test_frontend_openapi_json_is_up_to_date() -> None:
    expected = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"

    assert FRONTEND_OPENAPI.is_file(), "run: uv run python -m scripts.export_openapi ../frontend/openapi.json"
    assert FRONTEND_OPENAPI.read_text(encoding="utf-8") == expected, (
        "frontend/openapi.json is stale — run: uv run python -m scripts.export_openapi ../frontend/openapi.json "
        "&& (cd ../frontend && npm run gen:api)"
    )
