"""Authentication and user session routes (spec §5)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import Unauthorized
from app.core.security import create_access_token, verify_password
from app.domain.models.enums import Role
from app.domain.models.master import Store
from app.domain.models.users import AppUser
from app.domain.schemas.common import StoreRef
from app.domain.schemas.dtos import LoginRequest, MeDTO, TokenResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: DbSession) -> TokenResponse:
    raw_username = body.username.strip()
    clean_username = raw_username.split("@")[0] if "@" in raw_username else raw_username
    stmt = select(AppUser).where((AppUser.username == raw_username) | (AppUser.username == clean_username))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Invalid username or password")

    token, expires_in = create_access_token(
        user_id=user.user_id,
        role=user.role,
        store_id=user.store_id,
    )
    return TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get("/me", response_model=MeDTO)
async def get_me(current_user: CurrentUser, session: DbSession) -> MeDTO:
    store_ref: StoreRef | None = None
    if current_user.store_id is not None:
        stmt = select(Store).where(Store.store_id == current_user.store_id)
        result = await session.execute(stmt)
        store = result.scalar_one_or_none()
        if store:
            store_ref = StoreRef(store_id=store.store_id, name=store.name)

    return MeDTO(
        user_id=current_user.user_id,
        name=current_user.name,
        role="STORE_SUPERVISOR" if current_user.role == Role.STORE_SUPERVISOR.value else "SUPER_ADMIN",
        store=store_ref,
    )
