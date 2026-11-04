"""Recommendation service: lists inbox, delivers detail with viewer-scoped evidence, and processes actions."""

from __future__ import annotations

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFound, PermissionDenied
from app.domain.models.enums import RecStatus, Role
from app.domain.models.master import Product, Store
from app.domain.models.observability import DecisionEvidence
from app.domain.models.planning import Recommendation
from app.domain.models.transfers import TransferOrder
from app.domain.models.users import AppUser
from app.domain.schemas.common import Counterpart, Page, ProductRef, StoreRef
from app.domain.schemas.dtos import (
    Evidence,
    RecommendationDetailDTO,
    RecommendationDTO,
)

_evidence_adapter = TypeAdapter(Evidence)


class RecommendationService:
    async def list_inbox(
        self,
        session: AsyncSession,
        user: AppUser,
        store_id: UUID | None = None,
        status: str | None = None,
        rec_type: str | None = None,
        priority: str | None = None,
        product_id: UUID | None = None,
        page: int = 1,
        page_size: int = 25,
        sort: str | None = None,
        q: str | None = None,
    ) -> Page[RecommendationDTO]:
        stmt = (
            select(Recommendation, Store, Product)
            .join(Store, Store.store_id == Recommendation.store_id)
            .join(Product, Product.product_id == Recommendation.product_id)
        )

        # Viewer store scoping
        if user.role == Role.STORE_SUPERVISOR.value:
            stmt = stmt.where(Recommendation.store_id == user.store_id)
        elif store_id is not None:
            stmt = stmt.where(Recommendation.store_id == store_id)

        if status:
            stmt = stmt.where(Recommendation.status == status)
        if rec_type:
            stmt = stmt.where(Recommendation.rec_type == rec_type)
        if priority:
            stmt = stmt.where(Recommendation.priority == priority)
        if product_id:
            stmt = stmt.where(Recommendation.product_id == product_id)
        if q:
            term = f"%{q.strip()}%"
            stmt = stmt.where(Product.name.ilike(term) | Product.sku.ilike(term))

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one() or 0

        # Sorting: priority uses stored rank (0=HIGH, 1=NORMAL); default to priority_rank ASC, created_at ASC
        if sort:
            is_desc = sort.startswith("-")
            field = sort.lstrip("+-")
            if field == "priority":
                stmt = stmt.order_by(desc(Recommendation.priority_rank) if is_desc else Recommendation.priority_rank)
            elif field == "created_at":
                stmt = stmt.order_by(desc(Recommendation.created_at) if is_desc else Recommendation.created_at)
            elif field == "qty":
                stmt = stmt.order_by(desc(Recommendation.qty) if is_desc else Recommendation.qty)
            else:
                stmt = stmt.order_by(Recommendation.priority_rank.asc(), Recommendation.created_at.asc())
        else:
            stmt = stmt.order_by(Recommendation.priority_rank.asc(), Recommendation.created_at.asc())

        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        result = await session.execute(stmt)
        rows = result.all()

        rec_ids = [r[0].rec_id for r in rows]
        transfer_map: dict[UUID, tuple[UUID, str, int]] = {}
        if rec_ids:
            t_stmt = (
                select(TransferOrder.source_rec_id, TransferOrder.from_store_id, Store.name, TransferOrder.qty)
                .join(Store, Store.store_id == TransferOrder.from_store_id)
                .where(TransferOrder.source_rec_id.in_(rec_ids))
            )
            t_res = await session.execute(t_stmt)
            for s_rec_id, f_store_id, s_name, t_qty in t_res.all():
                transfer_map[s_rec_id] = (f_store_id, s_name, t_qty)

        items: list[RecommendationDTO] = []
        for rec, store, prod in rows:
            counterpart: Counterpart | None = None
            if rec.rec_id in transfer_map:
                f_store_id, s_name, t_qty = transfer_map[rec.rec_id]
                counterpart = Counterpart(
                    store=StoreRef(store_id=f_store_id, name=s_name),
                    qty=t_qty,
                )

            items.append(
                RecommendationDTO(
                    rec_id=rec.rec_id,
                    run_id=rec.run_id,
                    store=StoreRef(store_id=store.store_id, name=store.name),
                    product=ProductRef(
                        product_id=prod.product_id,
                        sku=prod.sku,
                        name=prod.name,
                        category=prod.category,
                    ),
                    rec_type=rec.rec_type,  # type: ignore[arg-type]
                    status=rec.status,  # type: ignore[arg-type]
                    priority="HIGH" if rec.priority == "HIGH" else "NORMAL",
                    qty=rec.qty,
                    lost_revenue=rec.lost_sales_value,
                    explanation=rec.explanation,
                    counterpart=counterpart,
                    created_at=rec.created_at,
                )
            )

        return Page[RecommendationDTO](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_detail(self, session: AsyncSession, rec_id: UUID, user: AppUser) -> RecommendationDetailDTO:
        stmt = (
            select(Recommendation, Store, Product)
            .join(Store, Store.store_id == Recommendation.store_id)
            .join(Product, Product.product_id == Recommendation.product_id)
            .where(Recommendation.rec_id == rec_id)
        )
        res = await session.execute(stmt)
        row = res.one_or_none()
        if not row:
            raise NotFound(f"Recommendation {rec_id} not found")

        rec, store, prod = row
        if user.role == Role.STORE_SUPERVISOR.value and rec.store_id != user.store_id:
            raise PermissionDenied("Store supervisor cannot view recommendations for another store")

        # Fetch evidence
        ev_stmt = select(DecisionEvidence).where(DecisionEvidence.rec_id == rec_id)
        ev_res = await session.execute(ev_stmt)
        ev_obj = ev_res.scalar_one_or_none()

        parsed_evidence: Evidence | None = None
        if ev_obj and ev_obj.data:
            try:
                raw_ev = dict(ev_obj.data)
                # Viewer scoping for TransferEvidence (D-32):
                # Donor surplus and protected requirement are visible only to Super Admin and donor supervisor.
                if raw_ev.get("kind") == "TRANSFER" and user.role == Role.STORE_SUPERVISOR.value:
                    donor_info = raw_ev.get("donor")
                    donor_id = donor_info.get("store", {}).get("store_id") if donor_info else None
                    if str(user.store_id) != str(donor_id):
                        raw_ev["donor_surplus"] = None
                        raw_ev["donor_protected_requirement"] = None
                        raw_ev["donor_keeps_requirement"] = True

                parsed_evidence = _evidence_adapter.validate_python(raw_ev)
            except Exception:
                pass

        # Counterpart
        counterpart: Counterpart | None = None
        t_stmt = (
            select(TransferOrder.from_store_id, Store.name, TransferOrder.qty)
            .join(Store, Store.store_id == TransferOrder.from_store_id)
            .where(TransferOrder.source_rec_id == rec_id)
        )
        t_res = await session.execute(t_stmt)
        t_row = t_res.one_or_none()
        if t_row:
            counterpart = Counterpart(
                store=StoreRef(store_id=t_row[0], name=t_row[1]),
                qty=t_row[2],
            )

        dto = RecommendationDTO(
            rec_id=rec.rec_id,
            run_id=rec.run_id,
            store=StoreRef(store_id=store.store_id, name=store.name),
            product=ProductRef(
                product_id=prod.product_id,
                sku=prod.sku,
                name=prod.name,
                category=prod.category,
            ),
            rec_type=rec.rec_type,  # type: ignore[arg-type]
            status=rec.status,  # type: ignore[arg-type]
            priority="HIGH" if rec.priority == "HIGH" else "NORMAL",
            qty=rec.qty,
            lost_revenue=rec.lost_sales_value,
            explanation=rec.explanation,
            counterpart=counterpart,
            created_at=rec.created_at,
        )

        return RecommendationDetailDTO(
            recommendation=dto,
            evidence=parsed_evidence,
        )

    async def action(
        self,
        session: AsyncSession,
        rec_id: UUID,
        action: str,
        user: AppUser,
        qty: int | None = None,
        reason: str | None = None,
    ) -> RecommendationDTO:
        rec = await session.get(Recommendation, rec_id)
        if not rec:
            raise NotFound(f"Recommendation {rec_id} not found")

        if user.role == Role.STORE_SUPERVISOR.value and rec.store_id != user.store_id:
            raise PermissionDenied("Store supervisor cannot act on another store's recommendation")

        if rec.status not in (RecStatus.PENDING.value, RecStatus.NEEDS_REVIEW.value):
            raise ConflictError(f"Recommendation is in status {rec.status} and cannot be acted on")

        if action == "ACCEPT":
            rec.status = RecStatus.ACCEPTED.value
        elif action == "REJECT":
            rec.status = RecStatus.REJECTED.value
            if reason:
                rec.reason = reason
        elif action == "EDIT":
            rec.status = RecStatus.EDITED.value
            if qty is not None:
                rec.qty = qty
        else:
            raise ConflictError(f"Unknown recommendation action: {action}")

        await session.commit()
        await session.refresh(rec)

        detail = await self.get_detail(session, rec_id, user)
        return detail.recommendation
