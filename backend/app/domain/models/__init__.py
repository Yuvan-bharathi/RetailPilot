"""SQLAlchemy models (CD-1, CD-2). Import every model module here so Alembic sees the tables."""

from app.domain.models.base import Base

__all__ = ["Base"]
