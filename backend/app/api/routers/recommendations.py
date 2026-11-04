"""Recommendation routes (spec §5, SD-10)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.domain.schemas.common import Page, PageParams, Priority
from app.domain.schemas.dtos import RecommendationDetailDTO, RecommendationDTO, RecStatus, RecType
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["recommendations"])
Paging = Annotated[PageParams, Query()]


class RecActionRequest(BaseModel):
    action: Literal["ACCEPT", "REJECT", "EDIT"]
    qty: int | None = Field(default=None, ge=0)
    reason: str | None = None


@router.get("/recommendations", response_model=Page[RecommendationDTO])
async def list_recommendations(
    current_user: CurrentUser,
    session: DbSession,
    paging: Paging,
    store_id: UUID | None = None,
    status: RecStatus | None = None,
    rec_type: Annotated[RecType | None, Query(alias="type")] = None,
    priority: Priority | None = None,
    product_id: UUID | None = None,
) -> Page[RecommendationDTO]:
    """Lists inbox recommendations with bounded offset pagination and rank sorting."""
    service = RecommendationService()
    return await service.list_inbox(
        session=session,
        user=current_user,
        store_id=store_id,
        status=status,
        rec_type=rec_type,
        priority=priority,
        product_id=product_id,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        q=paging.q,
    )


@router.get("/recommendations/{rec_id}", response_model=RecommendationDetailDTO)
async def get_recommendation(
    rec_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> RecommendationDetailDTO:
    """Returns single recommendation detail with viewer-scoped evidence."""
    service = RecommendationService()
    return await service.get_detail(session, rec_id, current_user)


@router.post("/recommendations/{rec_id}/action", response_model=RecommendationDTO)
async def act_on_recommendation(
    rec_id: UUID,
    body: RecActionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> RecommendationDTO:
    """Accepts, rejects, or edits a recommendation."""
    service = RecommendationService()
    return await service.action(
        session=session,
        rec_id=rec_id,
        action=body.action,
        user=current_user,
        qty=body.qty,
        reason=body.reason,
    )
