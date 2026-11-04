"""FastAPI application factory.

Run with: uv run uvicorn app.main:app --reload --loop app.core.db:selector_event_loop
(the selector event loop that psycopg's async driver needs on Windows; harmless elsewhere).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute

from app import __version__
from app.api import api_router
from app.api.routers import health
from app.core.config import get_settings
from app.core.db import dispose_engines
from app.core.errors import ErrorResponse, register_error_handlers
from app.core.logging import configure_logging

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 501)
}


def _operation_id(route: APIRoute) -> str:
    """Operation ids = handler names (e.g. list_recommendations) for readable generated TS types."""
    return route.name


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engines()  # close pooled connections on shutdown


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RetailPilot AI API",
        version=__version__,
        description="AI replenishment platform for multi-store FMCG retail.",
        responses=ERROR_RESPONSES,
        generate_unique_id_function=_operation_id,
        lifespan=_lifespan,
    )
    # D-40: compress larger responses; JSON is serialised by Pydantic through the declared response models
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
