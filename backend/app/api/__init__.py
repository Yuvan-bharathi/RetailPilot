"""HTTP API: `api_router` collects all real /api/v1 routers (spec §5)."""

from fastapi import APIRouter

from app.api.routers import (
    approvals,
    auth,
    business_rules,
    dashboard,
    inventory,
    notifications,
    purchase_orders,
    recommendations,
    runs,
    stores,
    transfers,
)

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
api_router.include_router(auth.router)
api_router.include_router(stores.router)
api_router.include_router(runs.router)
api_router.include_router(dashboard.router)
api_router.include_router(recommendations.router)
api_router.include_router(purchase_orders.router)
api_router.include_router(approvals.router)
api_router.include_router(transfers.router)
api_router.include_router(inventory.router)
api_router.include_router(notifications.router)
api_router.include_router(business_rules.router)
