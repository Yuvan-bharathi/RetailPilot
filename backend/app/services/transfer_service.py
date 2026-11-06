"""Stock transfer service: destination acceptance, donor approval, dispatch, and receiving per SD-12."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFound, PermissionDenied
from app.domain.models.enums import ApprovalDecision, MovementType, Role, TransferStatus
from app.domain.models.inventory import Batch, InventoryMovement, InventoryPosition
from app.domain.models.master import Product, Store
from app.domain.models.transfers import Approval, TransferOrder
from app.domain.models.users import AppUser
from app.domain.schemas.common import Page, ProductRef, StoreRef
from app.domain.schemas.dtos import TransferOrderDTO
from app.services.agent_decision_service import update_outcome
from app.services.cache_service import CacheService


class TransferService:
    def __init__(self, cache_service: CacheService | None = None) -> None:
        self.cache_service = cache_service or CacheService()

    async def list_transfers(
        self,
        session: AsyncSession,
        user: AppUser,
        store_id: UUID | None = None,
        status: str | None = None,
        product_id: UUID | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[TransferOrderDTO]:
        stmt = (
            select(TransferOrder, Store, Product)
            .join(Store, Store.store_id == TransferOrder.to_store_id)
            .join(Product, Product.product_id == TransferOrder.product_id)
            .order_by(desc(TransferOrder.created_at))
        )

        if user.role == Role.STORE_SUPERVISOR.value:
            stmt = stmt.where(
                (TransferOrder.from_store_id == user.store_id) | (TransferOrder.to_store_id == user.store_id)
            )
        elif store_id is not None:
            stmt = stmt.where(
                (TransferOrder.from_store_id == store_id) | (TransferOrder.to_store_id == store_id)
            )

        if status:
            stmt = stmt.where(TransferOrder.status == status)
        if product_id:
            stmt = stmt.where(TransferOrder.product_id == product_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one() or 0

        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await session.execute(stmt)
        rows = result.all()

        items = [await self._build_dto(session, t, user) for t, _, _ in rows]
        return Page[TransferOrderDTO](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_transfer(self, session: AsyncSession, transfer_id: UUID, user: AppUser) -> TransferOrderDTO:
        t = await session.get(TransferOrder, transfer_id)
        if not t:
            raise NotFound(f"Transfer order {transfer_id} not found")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id not in (t.from_store_id, t.to_store_id):
            raise PermissionDenied("Store supervisor not involved in this transfer")

        return await self._build_dto(session, t, user)

    async def accept(self, session: AsyncSession, transfer_id: UUID, user: AppUser) -> TransferOrderDTO:
        """Destination store supervisor accepts the transfer requirement (SD-12 step 1)."""
        t = await session.get(TransferOrder, transfer_id, with_for_update=True)
        if not t:
            raise NotFound(f"Transfer order {transfer_id} not found")

        if t.status != TransferStatus.PROPOSED.value:
            raise ConflictError(f"Transfer is in status {t.status}, expected PROPOSED")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != t.to_store_id:
            raise PermissionDenied("Only the destination store supervisor may accept this transfer")

        now = datetime.now(UTC)
        t.status = TransferStatus.DEST_ACCEPTED.value
        t.dest_accepted_by = user.user_id

        # Record approval
        appr = Approval(
            approval_id=uuid.uuid4(),
            entity_type="TRANSFER",
            entity_id=t.transfer_id,
            level="DEST",
            store_id=t.to_store_id,
            approver_id=user.user_id,
            decision=ApprovalDecision.APPROVED.value,
            decided_at=now,
        )
        session.add(appr)

        # Apply soft reservation: receiver incoming += qty, donor reserved += qty
        await self._adjust_commitment(session, t.to_store_id, t.product_id, incoming_delta=t.qty)
        await self._adjust_commitment(session, t.from_store_id, t.product_id, reserved_delta=t.qty)
        await update_outcome(session, action="ACCEPT", user_id=user.user_id, transfer_ids=[t.transfer_id])

        await session.commit()
        self.cache_service.invalidate_store_keys(
            [t.from_store_id, t.to_store_id], ["inbox", "dash", "inv", "twin"]
        )
        return await self._build_dto(session, t, user)

    async def approve_release(
        self, session: AsyncSession, transfer_id: UUID, user: AppUser
    ) -> TransferOrderDTO:
        """Donor store supervisor approves releasing surplus stock (SD-12 step 2)."""
        t = await session.get(TransferOrder, transfer_id, with_for_update=True)
        if not t:
            raise NotFound(f"Transfer order {transfer_id} not found")

        if t.status != TransferStatus.DEST_ACCEPTED.value:
            raise ConflictError(f"Transfer is in status {t.status}, expected DEST_ACCEPTED")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != t.from_store_id:
            raise PermissionDenied("Only the donor store supervisor may approve release")

        now = datetime.now(UTC)
        t.status = TransferStatus.DONOR_APPROVED.value
        t.donor_approved_by = user.user_id

        appr = Approval(
            approval_id=uuid.uuid4(),
            entity_type="TRANSFER",
            entity_id=t.transfer_id,
            level="DONOR",
            store_id=t.from_store_id,
            approver_id=user.user_id,
            decision=ApprovalDecision.APPROVED.value,
            decided_at=now,
        )
        session.add(appr)

        await session.commit()
        self.cache_service.invalidate_store_keys(
            [t.from_store_id, t.to_store_id], ["inbox", "dash", "inv", "twin"]
        )
        return await self._build_dto(session, t, user)

    async def reject(
        self, session: AsyncSession, transfer_id: UUID, reason: str, user: AppUser
    ) -> TransferOrderDTO:
        """Destination or donor supervisor rejects the transfer."""
        t = await session.get(TransferOrder, transfer_id, with_for_update=True)
        if not t:
            raise NotFound(f"Transfer order {transfer_id} not found")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id not in (t.from_store_id, t.to_store_id):
            raise PermissionDenied("User is not a party to this transfer")

        if t.status in (
            TransferStatus.DISPATCHED.value,
            TransferStatus.RECEIVED.value,
            TransferStatus.CANCELLED.value,
        ):
            raise ConflictError(f"Transfer in status {t.status} cannot be rejected")

        # If it was DEST_ACCEPTED or DONOR_APPROVED, release the reservations
        if t.status in (TransferStatus.DEST_ACCEPTED.value, TransferStatus.DONOR_APPROVED.value):
            await self._adjust_commitment(session, t.to_store_id, t.product_id, incoming_delta=-t.qty)
            await self._adjust_commitment(session, t.from_store_id, t.product_id, reserved_delta=-t.qty)

        now = datetime.now(UTC)
        t.status = TransferStatus.REJECTED.value

        appr = Approval(
            approval_id=uuid.uuid4(),
            entity_type="TRANSFER",
            entity_id=t.transfer_id,
            level="DONOR" if user.store_id == t.from_store_id else "DEST",
            store_id=user.store_id,
            approver_id=user.user_id,
            decision=ApprovalDecision.REJECTED.value,
            reason=reason,
            decided_at=now,
        )
        session.add(appr)
        await update_outcome(
            session, action="REJECT", user_id=user.user_id, reason=reason, transfer_ids=[t.transfer_id]
        )

        await session.commit()
        self.cache_service.invalidate_store_keys(
            [t.from_store_id, t.to_store_id], ["inbox", "dash", "inv", "twin"]
        )
        return await self._build_dto(session, t, user)

    async def dispatch(self, session: AsyncSession, transfer_id: UUID, user: AppUser) -> TransferOrderDTO:
        """Donor store marks stock as dispatched, posting TRANSFER_OUT to ledger."""
        t = await session.get(TransferOrder, transfer_id, with_for_update=True)
        if not t:
            raise NotFound(f"Transfer order {transfer_id} not found")

        if t.status != TransferStatus.DONOR_APPROVED.value:
            raise ConflictError(f"Transfer is in status {t.status}, expected DONOR_APPROVED")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != t.from_store_id:
            raise PermissionDenied("Only the donor store supervisor may dispatch")

        now = datetime.now(UTC)
        t.status = TransferStatus.DISPATCHED.value
        t.dispatched_at = now

        # Post TRANSFER_OUT movement
        mov = InventoryMovement(
            movement_id=uuid.uuid4(),
            store_id=t.from_store_id,
            product_id=t.product_id,
            batch_id=t.batch_id,
            movement_type=MovementType.TRANSFER_OUT.value,
            qty=-t.qty,
            location="BACKROOM",
            reference_type="TRANSFER",
            reference_id=t.transfer_id,
            reason="stock transfer dispatch",
            user_id=user.user_id,
            business_date=now.date(),
            occurred_at=now,
        )
        session.add(mov)

        # Update donor inventory position: release reserved, deduct on_hand
        pos_stmt = select(InventoryPosition).where(
            InventoryPosition.store_id == t.from_store_id,
            InventoryPosition.product_id == t.product_id,
        )
        pos_res = await session.execute(pos_stmt)
        pos = pos_res.scalar_one_or_none()
        if pos:
            pos.reserved = max(0, pos.reserved - t.qty)
            pos.backroom_qty = max(0, pos.backroom_qty - t.qty)

        await session.commit()
        self.cache_service.invalidate_store_keys(
            [t.from_store_id, t.to_store_id], ["inbox", "dash", "inv", "twin"]
        )
        return await self._build_dto(session, t, user)

    async def receive(
        self,
        session: AsyncSession,
        transfer_id: UUID,
        received_qty: int,
        user: AppUser,
    ) -> TransferOrderDTO:
        """Destination store supervisor confirms receipt, posting TRANSFER_IN to ledger."""
        t = await session.get(TransferOrder, transfer_id, with_for_update=True)
        if not t:
            raise NotFound(f"Transfer order {transfer_id} not found")

        if t.status != TransferStatus.DISPATCHED.value:
            raise ConflictError(f"Transfer is in status {t.status}, expected DISPATCHED")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != t.to_store_id:
            raise PermissionDenied("Only the destination store supervisor may receive")

        now = datetime.now(UTC)
        t.status = TransferStatus.RECEIVED.value
        t.received_at = now
        t.received_qty = received_qty

        # Post TRANSFER_IN movement
        mov = InventoryMovement(
            movement_id=uuid.uuid4(),
            store_id=t.to_store_id,
            product_id=t.product_id,
            batch_id=t.batch_id,
            movement_type=MovementType.TRANSFER_IN.value,
            qty=received_qty,
            location="BACKROOM",
            reference_type="TRANSFER",
            reference_id=t.transfer_id,
            reason="stock transfer receipt",
            user_id=user.user_id,
            business_date=now.date(),
            occurred_at=now,
        )
        session.add(mov)

        # Update destination inventory position: release incoming, add to backroom
        pos_stmt = select(InventoryPosition).where(
            InventoryPosition.store_id == t.to_store_id,
            InventoryPosition.product_id == t.product_id,
        )
        pos_res = await session.execute(pos_stmt)
        pos = pos_res.scalar_one_or_none()
        if pos:
            pos.incoming = max(0, pos.incoming - t.qty)
            pos.backroom_qty += received_qty
        else:
            pos = InventoryPosition(
                store_id=t.to_store_id,
                product_id=t.product_id,
                shelf_qty=0,
                backroom_qty=received_qty,
                incoming=0,
                reserved=0,
            )
            session.add(pos)

        # If expiry aware batch, reassign store
        if t.batch_id:
            b_stmt = select(Batch).where(Batch.batch_id == t.batch_id)
            b_res = await session.execute(b_stmt)
            b_obj = b_res.scalar_one_or_none()
            if b_obj:
                b_obj.store_id = t.to_store_id

        await session.commit()
        self.cache_service.invalidate_store_keys(
            [t.from_store_id, t.to_store_id], ["inbox", "dash", "inv", "twin"]
        )
        return await self._build_dto(session, t, user)

    async def _adjust_commitment(
        self,
        session: AsyncSession,
        store_id: UUID,
        product_id: UUID,
        incoming_delta: int = 0,
        reserved_delta: int = 0,
    ) -> None:
        pos_stmt = select(InventoryPosition).where(
            InventoryPosition.store_id == store_id,
            InventoryPosition.product_id == product_id,
        )
        pos_res = await session.execute(pos_stmt)
        pos = pos_res.scalar_one_or_none()
        if pos:
            pos.incoming = max(0, pos.incoming + incoming_delta)
            pos.reserved = max(0, pos.reserved + reserved_delta)

    async def _build_dto(self, session: AsyncSession, t: TransferOrder, user: AppUser) -> TransferOrderDTO:
        from_store = await session.get(Store, t.from_store_id)
        to_store = await session.get(Store, t.to_store_id)
        prod = await session.get(Product, t.product_id)

        return TransferOrderDTO(
            transfer_id=t.transfer_id,
            product=ProductRef(
                product_id=t.product_id,
                sku=prod.sku if prod else "Unknown",
                name=prod.name if prod else "Unknown",
                category=prod.category if prod else "General",
            ),
            from_store=StoreRef(
                store_id=t.from_store_id,
                name=from_store.name if from_store else "Unknown",
            ),
            to_store=StoreRef(
                store_id=t.to_store_id,
                name=to_store.name if to_store else "Unknown",
            ),
            qty=t.qty,
            status=t.status,  # type: ignore[arg-type]
            is_expiry_aware=t.is_expiry_aware,
            transit_days=t.transit_days,
            transfer_cost=t.transfer_cost,
            created_at=t.created_at,
            received_qty=t.received_qty,
        )
