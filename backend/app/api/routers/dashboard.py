"""Dashboard routes (spec §5, SD-11)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, resolve_store_id
from app.domain.schemas.dtos import DashboardSummary, Period
from app.services.dashboard_service import DashboardService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(
    current_user: CurrentUser,
    session: DbSession,
    store_id: UUID | None = None,
    period: Period = "LAST_28_DAYS",
) -> DashboardSummary:
    """Returns aggregated executive/store dashboard KPIs. Store supervisor is scoped to own store."""
    scoped_store_id = resolve_store_id(current_user, store_id)
    service = DashboardService()
    return await service.get_summary(session, scoped_store_id, period)

