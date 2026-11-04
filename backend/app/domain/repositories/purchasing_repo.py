"""Purchasing repository: purchase orders, line queries, and committed spend."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.domain.models.enums import LineStatus, POStatus
from app.domain.models.master import Supplier, SupplierProduct
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.transfers import BusinessRule
from app.tools.types import BusinessRules, SupplierOffer


class PurchasingRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_committed_spend(self, week_start: date) -> Decimal:
        stmt = select(func.coalesce(func.sum(PurchaseOrder.total_value), Decimal("0"))).where(
            PurchaseOrder.created_at >= week_start,
            PurchaseOrder.status.in_(
                [POStatus.APPROVED.value, POStatus.SUBMITTED.value, POStatus.RECEIVED.value]
            ),
        )
        return Decimal(str(self.session.scalar(stmt) or Decimal("0")))

    def get_on_order_pending(self, store_ids: list[UUID]) -> dict[tuple[UUID, UUID], int]:
        """Qty of PENDING / ESCALATED lines on PENDING_L1 POs kept from earlier runs (D-14)."""
        if not store_ids:
            return {}
        stmt = (
            select(
                POLine.store_id,
                POLine.product_id,
                func.coalesce(func.sum(POLine.qty), 0).label("pending_qty"),
            )
            .join(PurchaseOrder, POLine.po_id == PurchaseOrder.po_id)
            .where(
                POLine.store_id.in_(store_ids),
                PurchaseOrder.status == POStatus.PENDING_L1.value,
                POLine.line_status.in_([LineStatus.PENDING.value, "ESCALATED"]),
            )
            .group_by(POLine.store_id, POLine.product_id)
        )
        rows = self.session.execute(stmt).all()
        return {(r.store_id, r.product_id): int(r.pending_qty) for r in rows}

    def get_offers(self, product_ids: list[UUID]) -> dict[UUID, list[SupplierOffer]]:
        if not product_ids:
            return {}
        stmt = (
            select(SupplierProduct, Supplier.is_active)
            .join(Supplier, SupplierProduct.supplier_id == Supplier.supplier_id)
            .where(SupplierProduct.product_id.in_(product_ids))
        )
        rows = self.session.execute(stmt).all()
        offers_by_prod: dict[UUID, list[SupplierOffer]] = {}
        for sp, is_active in rows:
            offer = SupplierOffer(
                supplier_id=sp.supplier_id,
                product_id=sp.product_id,
                unit_price=sp.price,
                lead_time_days=sp.lead_time_days,
                moq=sp.moq,
                order_pack_size=sp.order_pack_size,
                available=bool(is_active),
            )
            offers_by_prod.setdefault(sp.product_id, []).append(offer)
        return offers_by_prod

    def get_business_rules(self) -> BusinessRules:
        stmt = select(BusinessRule).where(BusinessRule.scope_store_id.is_(None))
        rules = {r.rule_key: r.value for r in self.session.scalars(stmt).all()}

        def _dec(key: str, default: str) -> Decimal:
            val = rules.get(key, default)
            if isinstance(val, dict):
                val = val.get("value", default)
            return Decimal(str(val))

        def _int(key: str, default: int) -> int:
            val = rules.get(key, default)
            if isinstance(val, dict):
                val = val.get("value", default)
            return int(val)

        def _str(key: str, default: str) -> Any:
            val = rules.get(key, default)
            if isinstance(val, dict):
                val = val.get("value", default)
            return str(val)

        return BusinessRules(
            po_l2_threshold=_dec("po_l2_threshold", "50000"),
            weekly_budget=_dec("weekly_budget", "500000"),
            order_fixed_cost=_dec("order_fixed_cost", "0"),
            l1_deadline_hours=_int("l1_deadline_hours", 24),
            deadline_action=_str("deadline_action", "ESCALATE"),
        )

    def set_explanation(self, po_id: UUID, explanation: str) -> None:
        stmt = update(PurchaseOrder).where(PurchaseOrder.po_id == po_id).values(explanation=explanation)
        self.session.execute(stmt)

    def get_pos_by_run(self, run_id: UUID) -> list[PurchaseOrder]:
        stmt = select(PurchaseOrder).where(PurchaseOrder.run_id == run_id)
        return list(self.session.scalars(stmt).all())

    def insert_purchase_orders(self, orders: list[PurchaseOrder]) -> list[PurchaseOrder]:
        if not orders:
            return []
        for o in orders:
            self.session.add(o)
        self.session.flush()
        return orders
