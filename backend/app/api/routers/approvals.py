"""Approval routes (spec §5, SD-10)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.services.approval_service import ApprovalRequest, ApprovalResult, ApprovalService

router = APIRouter(tags=["approvals"])


@router.post("/approvals", response_model=ApprovalResult)
async def create_approval(
    body: ApprovalRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResult:
    """Decides line-level L1 or PO-level L2 purchase order approval (SD-10)."""
    service = ApprovalService()
    return await service.decide(session, body, current_user)
