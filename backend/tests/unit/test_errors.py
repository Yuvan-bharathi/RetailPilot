"""The standard error body (spec §5) for every error path."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import (
    ConflictError,
    ErrorDetail,
    NotFound,
    PermissionDenied,
    Unauthorized,
    ValidationError,
    register_error_handlers,
)


class Payload(BaseModel):
    qty: int


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("PO is not pending")

    @app.get("/forbidden")
    def forbidden() -> None:
        raise PermissionDenied()

    @app.get("/missing")
    def missing() -> None:
        raise NotFound("PO not found")

    @app.get("/invalid")
    def invalid() -> None:
        raise ValidationError("reason required", details=[ErrorDetail(field="reason", message="required")])

    @app.get("/unauthorized")
    def unauthorized() -> None:
        raise Unauthorized()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected")

    @app.post("/payload")
    def payload(body: Payload) -> Payload:
        return body

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_build_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "status", "code", "message"),
    [
        ("/conflict", 409, "CONFLICT", "PO is not pending"),
        ("/forbidden", 403, "FORBIDDEN", "Permission denied"),
        ("/missing", 404, "NOT_FOUND", "PO not found"),
        ("/unauthorized", 401, "UNAUTHORIZED", "Not authenticated"),
        ("/boom", 500, "INTERNAL", "Internal error"),
    ],
)
def test_app_errors_use_standard_body(
    client: TestClient, path: str, status: int, code: str, message: str
) -> None:
    response = client.get(path)

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": message, "details": []}}


def test_business_validation_error_keeps_details(client: TestClient) -> None:
    response = client.get("/invalid")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION",
            "message": "reason required",
            "details": [{"field": "reason", "message": "required"}],
        }
    }


def test_request_validation_maps_to_validation_code(client: TestClient) -> None:
    response = client.post("/payload", json={"qty": "not-a-number"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION"
    assert error["details"][0]["field"] == "qty"


def test_unknown_route_maps_to_not_found(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_string_details_are_wrapped() -> None:
    err = ConflictError("x", details=["line 1 already decided"])

    assert err.details == [ErrorDetail(field=None, message="line 1 already decided")]
