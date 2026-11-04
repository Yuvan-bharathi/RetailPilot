"""In-app notification service (spec §5, SD-14, D-08)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.domain.models.users import AppUser, Notification


class NotificationDTO(BaseModel):
    notification_id: UUID
    message: str
    link: str | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationService:
    async def list_for_user(
        self,
        session: AsyncSession,
        user: AppUser,
        unread_only: bool = False,
    ) -> list[NotificationDTO]:
        stmt = (
            select(Notification)
            .where(
                (Notification.user_id == user.user_id)
                | (Notification.role == user.role)
                | (Notification.store_id == user.store_id)
            )
            .order_by(desc(Notification.created_at))
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))

        res = await session.execute(stmt)
        notifs = res.scalars().all()
        return [
            NotificationDTO(
                notification_id=n.notification_id,
                message=n.message,
                link=n.link,
                read_at=n.read_at,
                created_at=n.created_at,
            )
            for n in notifs
        ]

    async def mark_read(self, session: AsyncSession, notification_id: UUID, user: AppUser) -> NotificationDTO:
        n = await session.get(Notification, notification_id)
        if not n:
            raise NotFound(f"Notification {notification_id} not found")

        n.read_at = datetime.now(UTC)
        await session.commit()
        return NotificationDTO(
            notification_id=n.notification_id,
            message=n.message,
            link=n.link,
            read_at=n.read_at,
            created_at=n.created_at,
        )
