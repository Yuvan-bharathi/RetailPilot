"""Standard error handling (docs/02-technical-spec.md §5).

Every error response has the body
    {"error": {"code": "CONFLICT|FORBIDDEN|NOT_FOUND|VALIDATION", "message": str, "details": []}}

Services raise the exceptions below; routers never build error responses themselves.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)

HTTP_422 = 422  # literal: Starlette renamed the constant (UNPROCESSABLE_ENTITY -> UNPROCESSABLE_CONTENT)


class ErrorCode(StrEnum):
    CONFLICT = "CONFLICT"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    # Not listed in spec §5; used only for statuses the spec does not cover.
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL = "INTERNAL"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"  # contract stubs until Phase 6 (D-32)


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Base class for errors that map to a standard error response."""

    code: ErrorCode = ErrorCode.INTERNAL
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "Internal error"

    def __init__(self, message: str | None = None, details: Sequence[ErrorDetail | str] = ()) -> None:
        self.message = message or self.default_message
        self.details = [d if isinstance(d, ErrorDetail) else ErrorDetail(message=d) for d in details]
        super().__init__(self.message)


class ConflictError(AppError):
    """409 — the entity is not in a state that allows this action."""

    code = ErrorCode.CONFLICT
    status_code = status.HTTP_409_CONFLICT
    default_message = "Conflict with the current state"


class PermissionDenied(AppError):
    """403 — the user's role or store scope does not allow this action."""

    code = ErrorCode.FORBIDDEN
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "Permission denied"


class NotFound(AppError):
    """404 — the entity does not exist (or is not visible to the user)."""

    code = ErrorCode.NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "Not found"


class ValidationError(AppError):
    """422 — business validation failed (distinct from pydantic.ValidationError)."""

    code = ErrorCode.VALIDATION
    status_code = HTTP_422
    default_message = "Validation failed"


class Unauthorized(AppError):
    """401 — missing or invalid credentials."""

    code = ErrorCode.UNAUTHORIZED
    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Not authenticated"


class NotImplementedYet(AppError):
    """501 — the endpoint is part of the API contract but not implemented yet (D-32)."""

    code = ErrorCode.NOT_IMPLEMENTED
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    default_message = "Not implemented yet (planned for Phase 6)"


_STATUS_TO_CODE: dict[int, ErrorCode] = {
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    HTTP_422: ErrorCode.VALIDATION,
}


def error_response(
    status_code: int, code: ErrorCode, message: str, details: Sequence[ErrorDetail] = ()
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=list(details)))
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def _validation_details(errors: Sequence[Any]) -> list[ErrorDetail]:
    details: list[ErrorDetail] = []
    for err in errors:
        loc = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")]
        details.append(ErrorDetail(field=".".join(loc) or None, message=str(err.get("msg", "invalid"))))
    return details


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _request_validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        HTTP_422,
        ErrorCode.VALIDATION,
        "Request validation failed",
        _validation_details(exc.errors()),
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL)
    return error_response(exc.status_code, code, str(exc.detail))


async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", exc_info=exc)
    return error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL, "Internal error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
