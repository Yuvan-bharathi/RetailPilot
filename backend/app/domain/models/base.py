"""Declarative base and shared column types for all SQLAlchemy models (CD-1, CD-2, spec §10).

- UUID primary keys: generated in Python (`uuid4`) and by the server (`gen_random_uuid()`, for COPY loads).
- Money: NUMERIC(14,2) → `Decimal`. Quantities: `int`.
- `created_at` / `updated_at` (timestamptz, UTC) on every table.
- Relationships use `lazy="raise"` (D-39): related rows are never loaded implicitly; repositories ask for them with
  `selectinload` / `joinedload`, so a hidden N+1 query fails in tests instead of slowing production.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import DateTime, MetaData, Numeric, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MONEY = Numeric(14, 2, asdecimal=True)

Money = Annotated[Decimal, mapped_column(MONEY)]


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


def rel(*args: Any, **kwargs: Any) -> Any:
    """`relationship(…, lazy="raise")` — the only way models declare relationships (D-39)."""
    kwargs.setdefault("lazy", "raise")
    return relationship(*args, **kwargs)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Timestamps:
    """`created_at` / `updated_at` on every table (spec §10)."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
