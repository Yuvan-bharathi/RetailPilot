"""Notification routes (spec §5, SD-14)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.services.notification_service import NotificationDTO, NotificationService

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationDTO])
async def list_notifications(
    current_user: CurrentUser,
    session: DbSession,
    unread: bool = False,
) -> list[NotificationDTO]:
    """Returns in-app notifications for the current user or store."""
    service = NotificationService()
    return await service.list_for_user(session, current_user, unread_only=unread)


@router.post("/notifications/{notification_id}/read", response_model=NotificationDTO)
async def mark_notification_read(
    notification_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> NotificationDTO:
    """Marks an in-app notification as read."""
    service = NotificationService()
    return await service.mark_read(session, notification_id, current_user)
