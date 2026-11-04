"""Store routes (spec §5, CLAUDE.md rule 10)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.domain.models.enums import Role
from app.domain.models.master import Store
from app.domain.schemas.dtos import StoreDTO

router = APIRouter(tags=["stores"])


@router.get("/stores", response_model=list[StoreDTO])
async def list_stores(current_user: CurrentUser, session: DbSession) -> list[StoreDTO]:
    """Returns stores visible to the user: Super Admin sees all stores; Store Supervisor sees own store only."""
    stmt = select(Store).order_by(Store.code)
    if current_user.role == Role.STORE_SUPERVISOR.value:
        stmt = stmt.where(Store.store_id == current_user.store_id)

    result = await session.execute(stmt)
    stores = result.scalars().all()
    return [
        StoreDTO(
            store_id=s.store_id,
            code=s.code,
            name=s.name,
            region=s.region,
            store_type=s.store_type,
        )
        for s in stores
    ]
