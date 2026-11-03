"""FastAPI application factory. Run with: uv run uvicorn app.main:app --reload"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.api.routers import health
from app.core.config import get_settings
from app.core.errors import ErrorResponse, register_error_handlers
from app.core.logging import configure_logging

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": ErrorResponse} for status in (403, 404, 409, 422)
}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RetailPilot AI API",
        version=__version__,
        description="AI replenishment platform for multi-store FMCG retail.",
        responses=ERROR_RESPONSES,
    )
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
