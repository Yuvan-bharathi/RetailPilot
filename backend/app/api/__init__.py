"""HTTP API: `api_router` collects every /api/v1 router (added phase by phase)."""

from fastapi import APIRouter

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
