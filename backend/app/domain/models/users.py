"""Users and notifications (CD-2 "Users & access")."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, Timestamps, uuid_pk
from app.domain.models.enums import Role, check_in


class AppUser(Timestamps, Base):
    """A PoC user (CD-2 `User`; table `app_user` because `user` is reserved in PostgreSQL)."""

    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(check_in("role", Role), name="role"),
        # a Store Supervisor always belongs to exactly one store (rule 10)
        CheckConstraint("role <> 'STORE_SUPERVISOR' OR store_id IS NOT NULL", name="supervisor_has_store"),
    )

    user_id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)  # bcrypt
    is_active: Mapped[bool] = mapped_column(server_default="true")
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("store.store_id"), index=True)


class Notification(Timestamps, Base):
    """In-app notification for a user, a store's supervisors, or a role (D-08)."""

    __tablename__ = "notification"
    __table_args__ = (
        # unread notifications per user, newest first (D-38)
        Index(
            "ix_notification_user_unread",
            "user_id",
            "created_at",
            postgresql_where=text("read_at IS NULL"),
        ),
        CheckConstraint(f"role IS NULL OR {check_in('role', Role)}", name="role"),
        CheckConstraint(
            "role IS NOT NULL OR store_id IS NOT NULL OR user_id IS NOT NULL", name="has_audience"
        ),
    )

    notification_id: Mapped[uuid.UUID] = uuid_pk()
    role: Mapped[str | None] = mapped_column(Text)
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("store.store_id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
