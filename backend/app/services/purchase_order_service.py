"""Purchase order service: queries with viewer scoping, resolve needs-review, and close-short."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFound, PermissionDenied
from app.domain.models.enums import POStatus, Role
from app.domain.models.master import Product, Store, Supplier
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.users import AppUser
from app.domain.schemas.common import Counterpart, Page, ProductRef, StoreRef, SupplierRef
from app.domain.schemas.dtos import POLineDTO, PurchaseOrderDTO


class PurchaseOrderService:
    async def list_pos(
        self,
        session: AsyncSession,
        user: AppUser,
        store_id: UUID | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[PurchaseOrderDTO]:
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.lines).selectinload(POLine.purchase_order),
            )
            .order_by(desc(PurchaseOrder.created_at))
        )

        if status:
            stmt = stmt.where(PurchaseOrder.status == status)

        # Scoping filter
        if user.role == Role.STORE_SUPERVISOR.value:
            stmt = stmt.join(POLine, POLine.po_id == PurchaseOrder.po_id).where(POLine.store_id == user.store_id).distinct()
        elif store_id is not None:
            stmt = stmt.join(POLine, POLine.po_id == PurchaseOrder.po_id).where(POLine.store_id == store_id).distinct()

        # Count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one() or 0

        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await session.execute(stmt)
        pos = result.scalars().all()

        items = [await self._build_po_dto(session, po, user) for po in pos]
        return Page[PurchaseOrderDTO](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_po(self, session: AsyncSession, po_id: UUID, user: AppUser) -> PurchaseOrderDTO:
        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(PurchaseOrder.po_id == po_id)
        )
        res = await session.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise NotFound(f"Purchase order {po_id} not found")

        if user.role == Role.STORE_SUPERVISOR.value:
            has_line = any(ln.store_id == user.store_id for ln in po.lines)
            if not has_line:
                raise PermissionDenied("Store supervisor cannot view purchase orders without lines for their store")

        return await self._build_po_dto(session, po, user)

    async def resolve_needs_review(
        self,
        session: AsyncSession,
        po_id: UUID,
        decision: Literal["APPROVE", "REJECT"],
        reason: str,
        user: AppUser,
    ) -> PurchaseOrderDTO:
        if user.role != Role.SUPER_ADMIN.value:
            raise PermissionDenied("Only Super Admin can resolve NEEDS_REVIEW purchase orders")

        po = await session.get(PurchaseOrder, po_id)
        if not po:
            raise NotFound(f"Purchase order {po_id} not found")

        if po.status != POStatus.NEEDS_REVIEW.value:
            raise ConflictError(f"Purchase order is in status {po.status}, not NEEDS_REVIEW")

        if decision == "APPROVE":
            po.status = POStatus.PENDING_L1.value
        else:
            po.status = POStatus.REJECTED.value

        await session.commit()
        return await self.get_po(session, po_id, user)

    async def close_short(
        self,
        session: AsyncSession,
        po_id: UUID,
        reason: str,
        user: AppUser,
    ) -> PurchaseOrderDTO:
        if user.role != Role.SUPER_ADMIN.value:
            raise PermissionDenied("Only Super Admin can close-short purchase orders")

        stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).where(PurchaseOrder.po_id == po_id)
        res = await session.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise NotFound(f"Purchase order {po_id} not found")

        for line in po.lines:
            if line.received_qty < line.qty:
                line.short_closed_qty = line.qty - line.received_qty

        po.status = POStatus.RECEIVED.value
        await session.commit()
        return await self.get_po(session, po_id, user)

    async def _build_po_dto(self, session: AsyncSession, po: PurchaseOrder, user: AppUser) -> PurchaseOrderDTO:
        # Supplier ref
        sup_stmt = select(Supplier).where(Supplier.supplier_id == po.supplier_id)
        sup_res = await session.execute(sup_stmt)
        sup = sup_res.scalar_one_or_none()
        supplier_ref = SupplierRef(
            supplier_id=sup.supplier_id if sup else po.supplier_id,
            name=sup.name if sup else "Unknown",
        )

        # Preload products and stores
        prod_ids = [ln.product_id for ln in po.lines]
        store_ids = [ln.store_id for ln in po.lines]

        products_map: dict[UUID, Product] = {}
        if prod_ids:
            p_stmt = select(Product).where(Product.product_id.in_(prod_ids))
            p_res = await session.execute(p_stmt)
            products_map = {p.product_id: p for p in p_res.scalars().all()}

        stores_map: dict[UUID, Store] = {}
        if store_ids:
            s_stmt = select(Store).where(Store.store_id.in_(store_ids))
            s_res = await session.execute(s_stmt)
            stores_map = {s.store_id: s for s in s_res.scalars().all()}

        lines_dto: list[POLineDTO] = []
        other_stores_counterpart_dict: dict[UUID, int] = {}

        for line in po.lines:
            if user.role == Role.STORE_SUPERVISOR.value and line.store_id != user.store_id:
                other_stores_counterpart_dict[line.store_id] = (
                    other_stores_counterpart_dict.get(line.store_id, 0) + line.qty
                )
                continue

            prod = products_map.get(line.product_id)
            st = stores_map.get(line.store_id)
            lines_dto.append(
                POLineDTO(
                    po_line_id=line.po_line_id,
                    store=StoreRef(
                        store_id=line.store_id,
                        name=st.name if st else "Unknown",
                    ),
                    product=ProductRef(
                        product_id=line.product_id,
                        sku=prod.sku if prod else "Unknown",
                        name=prod.name if prod else "Unknown",
                        category=prod.category if prod else "General",
                    ),
                    qty=line.qty,
                    unit_price=line.unit_price,
                    line_value=Decimal(str(line.qty)) * line.unit_price,
                    line_status=line.line_status,  # type: ignore[arg-type]
                    received_qty=line.received_qty,
                )
            )

        other_store_lines = [
            Counterpart(
                store=StoreRef(
                    store_id=sid,
                    name=stores_map[sid].name if sid in stores_map else "Other Store",
                ),
                qty=c_qty,
            )
            for sid, c_qty in other_stores_counterpart_dict.items()
        ]

        return PurchaseOrderDTO(
            po_id=po.po_id,
            supplier=supplier_ref,
            status=po.status,  # type: ignore[arg-type]
            required_level=po.required_level,  # type: ignore[arg-type]
            total_value=po.total_value,
            l1_deadline=po.l1_deadline,
            parent_po_id=po.parent_po_id,
            flags=po.flags or [],
            lines=lines_dto,
            other_store_lines=other_store_lines,
            created_at=po.created_at,
        )
