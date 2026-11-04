"""HTTP API: `api_router` collects every /api/v1 router."""

from fastapi import APIRouter

from app.api.routers import contract

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
api_router.include_router(contract.router)
