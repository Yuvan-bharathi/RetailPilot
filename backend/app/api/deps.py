"""FastAPI dependencies: database session, authentication, and role/store scoping (spec §5, SD-10)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import PermissionDenied, Unauthorized
from app.core.security import decode_access_token
from app.domain.models.enums import Role
from app.domain.models.users import AppUser

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AppUser:
    """Extracts and validates the JWT Bearer token, loading the active AppUser."""
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized("Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise Unauthorized("Token payload missing subject")

    try:
        user_id = UUID(user_id_str)
    except ValueError as e:
        raise Unauthorized("Invalid user ID in token") from e

    stmt = select(AppUser).where(AppUser.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise Unauthorized("User not found or inactive")

    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]


def require_role(*allowed_roles: Role | str) -> Callable[[AppUser], Awaitable[AppUser]]:
    allowed_values = {r.value if isinstance(r, Role) else r for r in allowed_roles}

    async def _role_checker(user: CurrentUser) -> AppUser:
        if user.role not in allowed_values:
            raise PermissionDenied(f"Action requires one of roles: {', '.join(allowed_values)}")
        return user

    return _role_checker


RequireSuperAdmin = Annotated[AppUser, Depends(require_role(Role.SUPER_ADMIN))]


def resolve_store_id(user: AppUser, requested_store_id: UUID | None) -> UUID | None:
    """Enforces store scoping per viewer (spec §5, CLAUDE.md rule 10).

    Super Admin may query any store or all stores (None).
    Store Supervisor may only query their own store. If requested_store_id is provided and differs,
    raises PermissionDenied. If None, defaults to user.store_id.
    """
    if user.role == Role.SUPER_ADMIN.value:
        return requested_store_id

    # For Store Supervisor:
    if requested_store_id is not None and requested_store_id != user.store_id:
        raise PermissionDenied("Store supervisors are strictly scoped to their assigned store")

    return user.store_id
