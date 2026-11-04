"""Minimal row builders for integration tests (Core inserts; each returns the new primary key)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, insert

from app.domain.models import (
    AgentRun,
    Product,
    PurchaseOrder,
    Recommendation,
    Store,
    Supplier,
)


def _id() -> uuid.UUID:
    return uuid.uuid4()


def store(conn: Connection, **kw: Any) -> uuid.UUID:
    sid = _id()
    values = {
        "store_id": sid,
        "code": f"T{sid.hex[:6]}",
        "name": "Test store",
        "region": "Test",
        "store_type": "test",
        "display_capacity": 100,
    } | kw
    conn.execute(insert(Store).values(values))
    return sid


def product(conn: Connection, **kw: Any) -> uuid.UUID:
    pid = _id()
    values = {
        "product_id": pid,
        "sku": f"SKU-{pid.hex[:8]}",
        "name": "Test product",
        "category": "test",
        "brand": "Test",
        "cost_price": Decimal("60"),
        "selling_price": Decimal("100"),
    } | kw
    conn.execute(insert(Product).values(values))
    return pid


def supplier(conn: Connection) -> uuid.UUID:
    sid = _id()
    conn.execute(insert(Supplier).values(supplier_id=sid, name="Test supplier", default_lead_time_days=3))
    return sid


def agent_run(conn: Connection, **kw: Any) -> uuid.UUID:
    rid = _id()
    values = {"run_id": rid, "agent_name": "nightly", "status": "SUCCESS", "run_date": date(2026, 11, 3)} | kw
    conn.execute(insert(AgentRun).values(values))
    return rid


def recommendation(conn: Connection, store_id: uuid.UUID, product_id: uuid.UUID, **kw: Any) -> uuid.UUID:
    rec_id = _id()
    values = {
        "rec_id": rec_id,
        "run_id": kw.pop("run_id", None) or agent_run(conn, run_date=None, agent_name="test"),
        "store_id": store_id,
        "product_id": product_id,
        "rec_type": "REORDER",
        "qty": 10,
        "evidence": {"kind": "REORDER"},
    } | kw
    conn.execute(insert(Recommendation).values(values))
    return rec_id


def purchase_order(conn: Connection, supplier_id: uuid.UUID, run_id: uuid.UUID, **kw: Any) -> uuid.UUID:
    po_id = _id()
    values = {
        "po_id": po_id,
        "supplier_id": supplier_id,
        "run_id": run_id,
        "total_value": Decimal("1000"),
        "status": "PENDING_L1",
    } | kw
    conn.execute(insert(PurchaseOrder).values(values))
    return po_id
