"""Transfer repository: routes matrix, transfer orders, and incoming items."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.transfers import TransferOrder, TransferRoute


class TransferRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_route_matrix(self) -> dict[tuple[UUID, UUID], TransferRoute]:
        stmt = select(TransferRoute)
        routes = self.session.scalars(stmt).all()
        return {(r.from_store_id, r.to_store_id): r for r in routes}

    def insert_transfers(self, transfers: list[TransferOrder]) -> list[TransferOrder]:
        if not transfers:
            return []
        for t in transfers:
            self.session.add(t)
        self.session.flush()
        return transfers

