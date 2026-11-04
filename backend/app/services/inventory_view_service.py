"""Store inventory and movement ledger service (SD-15, D-37)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.domain.models.enums import Role
from app.domain.models.inventory import Batch, InventoryMovement, InventoryPosition
from app.domain.models.master import (
    Product,
    Store,
    StoreProduct,
    Supplier,
    SupplierProduct,
    SupplierStoreTerms,
)
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun
from app.domain.models.planning import Forecast
from app.domain.models.transfers import TransferOrder
from app.domain.models.users import AppUser
from app.domain.schemas.common import CursorPage, Page, ProductRef, StoreRef
from app.domain.schemas.cursor import MovementCursor, decode_movement_cursor, encode_movement_cursor
from app.domain.schemas.dtos import (
    BatchDTO,
    InventoryMovementDTO,
    InventoryRowDTO,
    InventorySummary,
    StockoutRisk,
    StoreInventoryPage,
)
from app.tools.requirement import RequirementCalculator


class InventoryViewService:
    async def get_view(
        self,
        session: AsyncSession,
        store_id: UUID,
        user: AppUser,
        category: str | None = None,
        risk: StockoutRisk | None = None,
        refill_only: bool = False,
        page: int = 1,
        page_size: int = 25,
        sort: str | None = None,
    ) -> StoreInventoryPage:
        store = await session.get(Store, store_id)
        if not store:
            raise NotFound(f"Store {store_id} not found")

        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != store_id:
            raise PermissionDenied("Store supervisor can only view their own store inventory")

        # Fetch all store products joined with product and inventory position
        stmt = (
            select(StoreProduct, Product, InventoryPosition)
            .join(Product, Product.product_id == StoreProduct.product_id)
            .outerjoin(
                InventoryPosition,
                (InventoryPosition.store_id == StoreProduct.store_id)
                & (InventoryPosition.product_id == StoreProduct.product_id),
            )
            .where(StoreProduct.store_id == store_id)
        )

        if category:
            stmt = stmt.where(Product.category == category)

        res = await session.execute(stmt)
        rows = res.all()

        prod_ids = [sp.product_id for sp, _, _ in rows]

        # Daily demand from the latest successful nightly run only (no run or no forecast → 0, never a guess)
        forecast_map: dict[UUID, float] = {}
        latest_run = (
            await session.execute(
                select(AgentRun.run_id, AgentRun.run_date)
                .where(AgentRun.agent_name == NIGHTLY_AGENT, AgentRun.status.in_(["SUCCESS", "PARTIAL"]))
                .order_by(AgentRun.run_date.desc().nulls_last(), AgentRun.started_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if prod_ids and latest_run is not None:
            f_res = await session.execute(
                select(Forecast.product_id, Forecast.daily_demand).where(
                    Forecast.run_id == latest_run.run_id,
                    Forecast.store_id == store_id,
                    Forecast.product_id.in_(prod_ids),
                )
            )
            forecast_map = {pid: float(dd) for pid, dd in f_res.all()}

        # Lead time of the supplier serving THIS store (rule 1): store terms → supplier-product → supplier default
        lead_map: dict[UUID, int] = {}
        if prod_ids:
            lead_res = await session.execute(
                select(
                    StoreProduct.product_id,
                    SupplierStoreTerms.lead_time_days,
                    SupplierProduct.lead_time_days,
                    Supplier.default_lead_time_days,
                )
                .select_from(StoreProduct)
                .outerjoin(
                    SupplierStoreTerms,
                    (SupplierStoreTerms.supplier_id == StoreProduct.preferred_supplier_id)
                    & (SupplierStoreTerms.store_id == StoreProduct.store_id),
                )
                .outerjoin(
                    SupplierProduct,
                    (SupplierProduct.supplier_id == StoreProduct.preferred_supplier_id)
                    & (SupplierProduct.product_id == StoreProduct.product_id),
                )
                .outerjoin(Supplier, Supplier.supplier_id == StoreProduct.preferred_supplier_id)
                .where(StoreProduct.store_id == store_id, StoreProduct.product_id.in_(prod_ids))
            )
            for pid, terms_lead, product_lead, default_lead in lead_res.all():
                lead_map[pid] = RequirementCalculator.lead_time(
                    terms_lead, product_lead, int(default_lead or 0)
                )
        data_day = (
            latest_run.run_date - timedelta(days=1) if latest_run and latest_run.run_date else date.today()
        )

        # Preload near-expiry batch quantities (<= 14 days)
        near_exp_map: dict[UUID, int] = {}
        cutoff = data_day + timedelta(days=14)
        if prod_ids:
            b_stmt = (
                select(Batch.product_id, func.sum(Batch.qty))
                .where(
                    Batch.store_id == store_id, Batch.product_id.in_(prod_ids), Batch.expiry_date <= cutoff
                )
                .group_by(Batch.product_id)
            )
            b_res = await session.execute(b_stmt)
            for pid, b_qty in b_res.all():
                near_exp_map[pid] = int(b_qty or 0)

        # Preload pending transfers
        pending_in_map: dict[UUID, int] = {}
        pending_out_map: dict[UUID, int] = {}
        if prod_ids:
            t_in = (
                select(TransferOrder.product_id, func.sum(TransferOrder.qty))
                .where(
                    TransferOrder.to_store_id == store_id,
                    TransferOrder.product_id.in_(prod_ids),
                    TransferOrder.status.in_(["PROPOSED", "DEST_ACCEPTED", "DONOR_APPROVED", "DISPATCHED"]),
                )
                .group_by(TransferOrder.product_id)
            )
            t_in_res = await session.execute(t_in)
            for pid, t_qty in t_in_res.all():
                pending_in_map[pid] = int(t_qty or 0)

            t_out = (
                select(TransferOrder.product_id, func.sum(TransferOrder.qty))
                .where(
                    TransferOrder.from_store_id == store_id,
                    TransferOrder.product_id.in_(prod_ids),
                    TransferOrder.status.in_(["DEST_ACCEPTED", "DONOR_APPROVED"]),
                )
                .group_by(TransferOrder.product_id)
            )
            t_out_res = await session.execute(t_out)
            for pid, t_qty in t_out_res.all():
                pending_out_map[pid] = int(t_qty or 0)

        # Build row list
        all_items: list[InventoryRowDTO] = []
        high_risk_count = 0
        med_risk_count = 0
        refill_needed_count = 0
        near_exp_total = 0
        shortage_count = 0

        for sp, prod, pos in rows:
            shelf_qty = pos.shelf_qty if pos else 0
            backroom_qty = pos.backroom_qty if pos else 0
            incoming = pos.incoming if pos else 0
            reserved = pos.reserved if pos else 0
            available = shelf_qty + backroom_qty + incoming - reserved

            daily_d = forecast_map.get(prod.product_id, 0.0)
            lead_days = lead_map.get(prod.product_id, 0)
            doc = float(round(RequirementCalculator.days_of_cover(available, daily_d), 1))
            item_risk = cast(
                StockoutRisk,
                RequirementCalculator.stockout_risk(available, daily_d, lead_days, sp.review_period_days),
            )
            if item_risk == "HIGH":
                high_risk_count += 1
            elif item_risk == "MEDIUM":
                med_risk_count += 1

            shelf_min = sp.min_display_qty
            refill = (shelf_qty < shelf_min) and (backroom_qty > 0)
            if refill:
                refill_needed_count += 1

            n_exp = near_exp_map.get(prod.product_id, 0)
            near_exp_total += n_exp

            own_req = RequirementCalculator.own_requirement(
                daily_d, lead_days, sp.review_period_days, sp.safety_stock_days, sp.min_display_qty
            )
            surplus_or_short = available - own_req
            if surplus_or_short < 0:
                shortage_count += 1

            row_dto = InventoryRowDTO(
                product=ProductRef(
                    product_id=prod.product_id,
                    sku=prod.sku,
                    name=prod.name,
                    category=prod.category,
                ),
                shelf_qty=shelf_qty,
                shelf_min=shelf_min,
                backroom_qty=backroom_qty,
                incoming=incoming,
                reserved=reserved,
                available=available,
                own_requirement=own_req,
                surplus_or_shortage=surplus_or_short,
                days_of_cover=doc,
                stockout_risk=item_risk,
                near_expiry_qty=n_exp,
                pending_transfer_in=pending_in_map.get(prod.product_id, 0),
                pending_transfer_out=pending_out_map.get(prod.product_id, 0),
                refill_from_backroom=refill,
            )
            all_items.append(row_dto)

        # Filters on candidate items
        filtered = all_items
        if risk:
            filtered = [it for it in filtered if it.stockout_risk == risk]
        if refill_only:
            filtered = [it for it in filtered if it.refill_from_backroom]

        # Sorting: stockout_risk uses business rank (HIGH=0, MEDIUM=1, LOW=2)
        risk_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        if sort:
            is_desc = sort.startswith("-")
            field = sort.lstrip("+-")
            if field == "stockout_risk":
                filtered.sort(key=lambda x: risk_rank[x.stockout_risk], reverse=is_desc)
            elif field == "days_of_cover":
                filtered.sort(key=lambda x: x.days_of_cover, reverse=is_desc)
            elif field == "shelf_qty":
                filtered.sort(key=lambda x: x.shelf_qty, reverse=is_desc)
            else:
                filtered.sort(key=lambda x: risk_rank[x.stockout_risk])
        else:
            filtered.sort(key=lambda x: risk_rank[x.stockout_risk])

        total = len(filtered)
        start = (page - 1) * page_size
        paged_items = filtered[start : start + page_size]

        summary = InventorySummary(
            products=len(all_items),
            high_risk=high_risk_count,
            medium_risk=med_risk_count,
            refill_needed=refill_needed_count,
            near_expiry_qty=near_exp_total,
            shortage_products=shortage_count,
        )

        return StoreInventoryPage(
            items=paged_items,
            total=total,
            page=page,
            page_size=page_size,
            store=StoreRef(store_id=store.store_id, name=store.name),
            summary=summary,
        )

    async def list_movements(
        self,
        session: AsyncSession,
        store_id: UUID,
        user: AppUser,
        cursor_token: str | None = None,
        page_size: int = 25,
        product_id: UUID | None = None,
        movement_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        q: str | None = None,
    ) -> CursorPage[InventoryMovementDTO]:
        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != store_id:
            raise PermissionDenied("Store supervisor can only view their own store movements")

        stmt = (
            select(InventoryMovement, Product)
            .join(Product, Product.product_id == InventoryMovement.product_id)
            .where(InventoryMovement.store_id == store_id)
        )

        if product_id:
            stmt = stmt.where(InventoryMovement.product_id == product_id)
        if movement_type:
            stmt = stmt.where(InventoryMovement.movement_type == movement_type)
        if date_from:
            stmt = stmt.where(InventoryMovement.business_date >= date_from)
        if date_to:
            stmt = stmt.where(InventoryMovement.business_date <= date_to)
        if q:
            term = f"%{q.strip()}%"
            stmt = stmt.where(Product.name.ilike(term) | Product.sku.ilike(term))

        # Cursor keyset paging: occurred_at DESC, movement_id DESC
        if cursor_token:
            cursor = decode_movement_cursor(cursor_token)
            stmt = stmt.where(
                (InventoryMovement.occurred_at < cursor.occurred_at)
                | (
                    (InventoryMovement.occurred_at == cursor.occurred_at)
                    & (InventoryMovement.movement_id < cursor.movement_id)
                )
            )

        stmt = stmt.order_by(desc(InventoryMovement.occurred_at), desc(InventoryMovement.movement_id)).limit(
            page_size + 1
        )
        res = await session.execute(stmt)
        rows = res.all()

        has_more = len(rows) > page_size
        slice_rows = rows[:page_size]

        items = [
            InventoryMovementDTO(
                movement_id=m.movement_id,
                product=ProductRef(
                    product_id=p.product_id,
                    sku=p.sku,
                    name=p.name,
                    category=p.category,
                ),
                movement_type=m.movement_type,  # type: ignore[arg-type]
                qty=m.qty,
                location=m.location,  # type: ignore[arg-type]
                reference=str(m.reference_id) if m.reference_id else None,
                reason=m.reason,
                occurred_at=m.occurred_at,
                business_date=m.business_date,
            )
            for m, p in slice_rows
        ]

        next_cursor: str | None = None
        if has_more and items:
            last_item = items[-1]
            next_cursor = encode_movement_cursor(
                MovementCursor(occurred_at=last_item.occurred_at, movement_id=last_item.movement_id)
            )

        return CursorPage[InventoryMovementDTO](
            items=items,
            next_cursor=next_cursor,
            page_size=page_size,
        )

    async def list_batches(
        self,
        session: AsyncSession,
        store_id: UUID,
        user: AppUser,
        product_id: UUID | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[BatchDTO]:
        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != store_id:
            raise PermissionDenied("Store supervisor can only view their own store batches")

        stmt = (
            select(Batch, Product)
            .join(Product, Product.product_id == Batch.product_id)
            .where(Batch.store_id == store_id, Batch.qty > 0)
        )
        if product_id:
            stmt = stmt.where(Batch.product_id == product_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one() or 0

        # FEFO order
        stmt = stmt.order_by(Batch.product_id, Batch.expiry_date.asc())
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        res = await session.execute(stmt)
        rows = res.all()

        today = date.today()
        items: list[BatchDTO] = []
        rank_counter: dict[UUID, int] = {}

        for b, p in rows:
            rank = rank_counter.get(b.product_id, 0) + 1
            rank_counter[b.product_id] = rank
            days_left = (b.expiry_date - today).days

            items.append(
                BatchDTO(
                    batch_id=b.batch_id,
                    product=ProductRef(
                        product_id=p.product_id,
                        sku=p.sku,
                        name=p.name,
                        category=p.category,
                    ),
                    batch_no=b.batch_no,
                    qty=b.qty,
                    expiry_date=b.expiry_date,
                    days_left=days_left,
                    fefo_rank=rank,
                    at_risk_qty=b.qty if days_left <= 7 else 0,
                )
            )

        return Page[BatchDTO](items=items, total=total, page=page, page_size=page_size)

    async def list_expiring(
        self,
        session: AsyncSession,
        store_id: UUID,
        user: AppUser,
        within_days: int = 14,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[BatchDTO]:
        if user.role == Role.STORE_SUPERVISOR.value and user.store_id != store_id:
            raise PermissionDenied("Store supervisor can only view their own store expiring stock")

        today = date.today()
        cutoff = today + timedelta(days=within_days)

        stmt = (
            select(Batch, Product)
            .join(Product, Product.product_id == Batch.product_id)
            .where(
                Batch.store_id == store_id,
                Batch.qty > 0,
                Batch.expiry_date <= cutoff,
            )
            .order_by(Batch.expiry_date.asc())
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one() or 0

        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        res = await session.execute(stmt)
        rows = res.all()

        items: list[BatchDTO] = []
        for rank, (b, p) in enumerate(rows, start=1):
            days_left = (b.expiry_date - today).days
            items.append(
                BatchDTO(
                    batch_id=b.batch_id,
                    product=ProductRef(
                        product_id=p.product_id,
                        sku=p.sku,
                        name=p.name,
                        category=p.category,
                    ),
                    batch_no=b.batch_no,
                    qty=b.qty,
                    expiry_date=b.expiry_date,
                    days_left=days_left,
                    fefo_rank=rank,
                    at_risk_qty=b.qty,
                )
            )

        return Page[BatchDTO](items=items, total=total, page=page, page_size=page_size)
