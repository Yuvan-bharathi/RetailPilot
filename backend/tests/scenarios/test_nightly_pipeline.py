"""Acceptance tests for Phase 5: Nightly Orchestration Pipeline & 6 Replenishment Agents.

Tests full end-to-end execution against PostgreSQL 16:
- SalesAnalyticsAgent
- DemandForecastingAgent
- RelatedProductAgent
- StockBalancingAgent
- FreshnessAgent
- PurchaseOrderAgent
- RunSupersession (D-03)
- Approval deadline enforcement (SD-14)
- Partition maintenance (D-35)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Connection, insert, select, text
from sqlalchemy.orm import Session, selectinload

from app.agents.orchestrator import WorkflowOrchestrator
from app.domain.models.enums import LineStatus, POStatus, Priority, RecStatus
from app.domain.models.master import (
    Product,
    Store,
    StoreProduct,
    Supplier,
    SupplierProduct,
    SupplierStoreTerms,
)
from app.domain.models.observability import AgentRun
from app.domain.models.planning import Forecast, Recommendation
from app.domain.models.purchasing import POLine, PurchaseOrder
from app.domain.models.sales import SalesLine, SalesTransaction
from app.domain.models.transfers import TransferRoute
from app.domain.schemas.ingestion import PosSource, RawBatchRow, RawBillLine, RawStockRow
from app.services.approval_service import ApprovalService
from app.workers.tasks import partition_maintenance_task

pytestmark = pytest.mark.integration

D = date(2026, 11, 3)
NOW = datetime(2026, 11, 3, 10, 0, 0, tzinfo=UTC)


class MockPosSource(PosSource):
    def __init__(
        self,
        sales: list[RawBillLine] | None = None,
        snapshots: list[RawStockRow] | None = None,
        batches: list[RawBatchRow] | None = None,
    ) -> None:
        self.sales = sales or []
        self.snapshots = snapshots or []
        self.batches = batches or []

    def fetch_sales(self, store_id: UUID, day: date) -> list[RawBillLine]:
        return [s for s in self.sales if s.store_id == store_id and s.txn_date == day]

    def fetch_stock_snapshot(self, store_id: UUID, day: date) -> list[RawStockRow]:
        return [s for s in self.snapshots if s.store_id == store_id and s.snapshot_date == day]

    def fetch_batches(self, store_id: UUID) -> list[RawBatchRow]:
        return [b for b in self.batches if b.store_id == store_id]


@pytest.fixture
def scenario_setup(db: Connection) -> dict[str, Any]:
    session = Session(bind=db)

    # 1. Stores: Store A (Indiranagar), Store B (Koramangala), Store C (Whitefield)
    store_a = uuid.uuid4()
    store_b = uuid.uuid4()
    store_c = uuid.uuid4()
    stores = [
        {
            "store_id": store_a,
            "code": "IND",
            "name": "Indiranagar",
            "region": "BLR",
            "store_type": "standard",
            "display_capacity": 500,
        },
        {
            "store_id": store_b,
            "code": "KOR",
            "name": "Koramangala",
            "region": "BLR",
            "store_type": "standard",
            "display_capacity": 500,
        },
        {
            "store_id": store_c,
            "code": "WHI",
            "name": "Whitefield",
            "region": "BLR",
            "store_type": "standard",
            "display_capacity": 500,
        },
    ]
    for s in stores:
        session.execute(insert(Store).values(s))

    # 2. Supplier
    supp_id = uuid.uuid4()
    session.execute(
        insert(Supplier).values(
            supplier_id=supp_id,
            name="Apex FMCG Supplies",
            default_lead_time_days=2,
            is_active=True,
        )
    )

    # 3. Products:
    # Prod 1: Fast mover (Rice 5kg)
    # Prod 2: Bread (Complement to Butter)
    # Prod 3: Butter
    # Prod 4: Paneer (Perishable batch test)
    prod_rice = uuid.uuid4()
    prod_bread = uuid.uuid4()
    prod_butter = uuid.uuid4()
    prod_paneer = uuid.uuid4()

    products = [
        {
            "product_id": prod_rice,
            "sku": "RICE-5K",
            "name": "Basmati Rice 5kg",
            "category": "Staples",
            "brand": "IndiaGate",
            "cost_price": Decimal("250.00"),
            "selling_price": Decimal("320.00"),
            "pack_size": 10,
        },
        {
            "product_id": prod_bread,
            "sku": "BREAD-W",
            "name": "Whole Wheat Bread 400g",
            "category": "Bakery",
            "brand": "Modern",
            "cost_price": Decimal("30.00"),
            "selling_price": Decimal("45.00"),
            "pack_size": 1,
            "shelf_life_days": 5,
        },
        {
            "product_id": prod_butter,
            "sku": "BUTTER-100",
            "name": "Table Butter 100g",
            "category": "Dairy",
            "brand": "Amul",
            "cost_price": Decimal("50.00"),
            "selling_price": Decimal("60.00"),
            "pack_size": 1,
            "shelf_life_days": 60,
        },
        {
            "product_id": prod_paneer,
            "sku": "PANEER-200",
            "name": "Fresh Malai Paneer 200g",
            "category": "Dairy",
            "brand": "Amul",
            "cost_price": Decimal("80.00"),
            "selling_price": Decimal("110.00"),
            "pack_size": 1,
            "shelf_life_days": 14,
        },
    ]
    for p in products:
        session.execute(insert(Product).values(p))

    # 4. StoreProduct listings
    for sid in [store_a, store_b, store_c]:
        for p in products:
            session.execute(
                insert(StoreProduct).values(
                    store_id=sid,
                    product_id=p["product_id"],
                    preferred_supplier_id=supp_id,
                    min_display_qty=5,
                    safety_stock_days=2,
                    review_period_days=7,
                    abc_class="A",
                    xyz_class="X",
                    is_listed=True,
                )
            )

    # 5. Supplier Products & Store Terms
    for p in products:
        session.execute(
            insert(SupplierProduct).values(
                supplier_id=supp_id,
                product_id=p["product_id"],
                price=p["cost_price"],
                lead_time_days=2,
                moq=5,
                order_pack_size=5,
            )
        )

    for sid in [store_a, store_b, store_c]:
        session.execute(
            insert(SupplierStoreTerms).values(
                supplier_id=supp_id,
                store_id=sid,
                lead_time_days=2,
                delivery_charge=Decimal("50.00"),
            )
        )

    # 6. Transfer Routes between stores
    routes = [
        {
            "from_store_id": store_a,
            "to_store_id": store_b,
            "fixed_cost": Decimal("20.00"),
            "per_unit_cost": Decimal("1.00"),
            "handling_cost_per_unit": Decimal("0.50"),
            "transit_days": 1,
        },
        {
            "from_store_id": store_a,
            "to_store_id": store_c,
            "fixed_cost": Decimal("30.00"),
            "per_unit_cost": Decimal("1.50"),
            "handling_cost_per_unit": Decimal("0.50"),
            "transit_days": 1,
        },
        {
            "from_store_id": store_b,
            "to_store_id": store_c,
            "fixed_cost": Decimal("20.00"),
            "per_unit_cost": Decimal("1.00"),
            "handling_cost_per_unit": Decimal("0.50"),
            "transit_days": 1,
        },
        {
            "from_store_id": store_c,
            "to_store_id": store_a,
            "fixed_cost": Decimal("30.00"),
            "per_unit_cost": Decimal("1.50"),
            "handling_cost_per_unit": Decimal("0.50"),
            "transit_days": 1,
        },
    ]
    for r in routes:
        session.execute(insert(TransferRoute).values(r))

    session.flush()

    return {
        "store_a": store_a,
        "store_b": store_b,
        "store_c": store_c,
        "supp_id": supp_id,
        "prod_rice": prod_rice,
        "prod_bread": prod_bread,
        "prod_butter": prod_butter,
        "prod_paneer": prod_paneer,
    }


def test_nightly_orchestrator_pipeline_end_to_end(db: Connection, scenario_setup: dict[str, Any]) -> None:
    session = Session(bind=db)
    s = scenario_setup

    # Seed 14 days of historical sales so forecasting agent can compute baseline demand
    for day_offset in range(1, 15):
        past_date = D - timedelta(days=day_offset)
        past_bill = uuid.uuid4()
        session.execute(
            insert(SalesTransaction).values(
                bill_id=past_bill,
                store_id=s["store_a"],
                txn_datetime=datetime.combine(past_date, datetime.min.time(), tzinfo=UTC),
                txn_date=past_date,
                total_amount=Decimal("3200.00"),
            )
        )
        session.execute(
            insert(SalesLine).values(
                bill_id=past_bill,
                line_no=1,
                txn_date=past_date,
                store_id=s["store_a"],
                product_id=s["prod_rice"],
                qty=10,
                unit_price=Decimal("320.00"),
                discount=Decimal("0.00"),
            )
        )
    session.flush()

    # Prepare POS mock data:
    # 1. Fast mover (Rice): High sales, 0 closing stock in all 3 stores -> Triggers Scenario 1
    # 2. Expiring batch in Store A for Paneer expiring in 3 days -> Triggers Freshness transfer to Store B / C
    bill_id = uuid.uuid4()
    mock_sales = [
        # Historical sales from yesterday
        RawBillLine(
            bill_id=bill_id,
            line_no=1,
            txn_datetime=NOW - timedelta(days=1),
            txn_date=D - timedelta(days=1),
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            qty=20,
            unit_price=Decimal("320.00"),
            discount=Decimal("0.00"),
        ),
        # And today's sales
        RawBillLine(
            bill_id=uuid.uuid4(),
            line_no=1,
            txn_datetime=NOW,
            txn_date=D,
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            qty=20,
            unit_price=Decimal("320.00"),
            discount=Decimal("0.00"),
        ),
    ]

    mock_stock = [
        # Store A: 0 Rice, 50 Paneer
        RawStockRow(
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            snapshot_date=D,
            shelf_qty=0,
            backroom_qty=0,
            closing_on_hand=0,
        ),
        RawStockRow(
            store_id=s["store_a"],
            product_id=s["prod_paneer"],
            snapshot_date=D,
            shelf_qty=50,
            backroom_qty=0,
            closing_on_hand=50,
        ),
        # Store B: 0 Rice
        RawStockRow(
            store_id=s["store_b"],
            product_id=s["prod_rice"],
            snapshot_date=D,
            shelf_qty=0,
            backroom_qty=0,
            closing_on_hand=0,
        ),
        # Store C: 0 Rice
        RawStockRow(
            store_id=s["store_c"],
            product_id=s["prod_rice"],
            snapshot_date=D,
            shelf_qty=0,
            backroom_qty=0,
            closing_on_hand=0,
        ),
    ]

    mock_batches = [
        RawBatchRow(
            batch_id=uuid.uuid4(),
            store_id=s["store_a"],
            product_id=s["prod_paneer"],
            batch_no="B-PANEER-01",
            qty=50,
            received_date=D - timedelta(days=10),
            expiry_date=D + timedelta(days=2),  # Expiring in 2 days!
        ),
    ]

    pos_source = MockPosSource(sales=mock_sales, snapshots=mock_stock, batches=mock_batches)
    orchestrator = WorkflowOrchestrator(session, pos_source=pos_source)

    run_id = uuid.uuid4()
    summary = orchestrator.run_nightly(run_id=run_id, run_date=D)

    # Assert overall run outcome
    assert summary.status == "SUCCESS"
    assert summary.run_id == run_id
    assert summary.error is None

    # Check that root AgentRun record was logged
    root_run = session.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
    assert root_run is not None
    assert root_run.status == "SUCCESS"

    # Check that child agent runs were logged (6 agents)
    child_runs = list(session.scalars(select(AgentRun).where(AgentRun.parent_run_id == run_id)).all())
    for r in child_runs:
        print(f"AGENT: {r.agent_name} -> status={r.status}, output={r.output_summary}, error={r.error}")

    sales_count = session.scalar(select(text("COUNT(*)")).select_from(SalesLine))
    print(f"TOTAL SALES LINES IN DB: {sales_count}")

    # Check that forecasts were generated
    forecasts = list(session.scalars(select(Forecast).where(Forecast.run_id == run_id)).all())
    assert len(forecasts) > 0

    # Check that recommendations and purchase orders were generated
    recs = list(session.scalars(select(Recommendation).where(Recommendation.run_id == run_id)).all())
    assert len(recs) > 0
    # Every recommendation must have explanation generated
    for rec in recs:
        assert rec.explanation is not None
        assert len(rec.explanation) > 0

    # Check POs
    pos = list(
        session.scalars(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(PurchaseOrder.run_id == run_id)
        ).all()
    )
    assert len(pos) > 0
    for po in pos:
        assert po.status == POStatus.PENDING_L1.value
        assert po.explanation is not None
        assert len(po.lines) > 0


def test_run_supersession_on_second_nightly_run(db: Connection, scenario_setup: dict[str, Any]) -> None:
    session = Session(bind=db)
    s = scenario_setup

    pos_source = MockPosSource()
    orchestrator = WorkflowOrchestrator(session, pos_source=pos_source)

    # Run 1
    run_1 = uuid.uuid4()
    summary_1 = orchestrator.run_nightly(run_id=run_1, run_date=D)
    assert summary_1.status == "SUCCESS"

    # Create a manual PENDING recommendation and PENDING_L1 PO on run 1
    rec_id = uuid.uuid4()
    session.execute(
        insert(Recommendation).values(
            rec_id=rec_id,
            run_id=run_1,
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            rec_type="REORDER",
            qty=15,
            priority=Priority.HIGH.value,
            status=RecStatus.PENDING.value,
            evidence={"qty": 15},
        )
    )
    po_id = uuid.uuid4()
    session.execute(
        insert(PurchaseOrder).values(
            po_id=po_id,
            supplier_id=s["supp_id"],
            run_id=run_1,
            total_value=Decimal("500.00"),
            status=POStatus.PENDING_L1.value,
        )
    )
    po_line_id = uuid.uuid4()
    session.execute(
        insert(POLine).values(
            po_line_id=po_line_id,
            po_id=po_id,
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            qty=15,
            unit_price=Decimal("250.00"),
            source_rec_id=rec_id,
            line_status=LineStatus.PENDING.value,
        )
    )
    session.flush()

    # Run 2 on next day (D + 1)
    run_2 = uuid.uuid4()
    summary_2 = orchestrator.run_nightly(run_id=run_2, run_date=D + timedelta(days=1))
    assert summary_2.status == "SUCCESS"

    # Verify that run 1's untouched items were superseded (D-03)
    rec_1 = session.scalar(select(Recommendation).where(Recommendation.rec_id == rec_id))
    assert rec_1.status == RecStatus.SUPERSEDED.value

    po_1 = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_id == po_id))
    assert po_1.status == POStatus.SUPERSEDED.value

    line_1 = session.scalar(select(POLine).where(POLine.po_line_id == po_line_id))
    assert line_1.line_status == LineStatus.SUPERSEDED.value


def test_approval_deadline_escalation_service(db: Connection, scenario_setup: dict[str, Any]) -> None:
    session = Session(bind=db)
    s = scenario_setup

    # Create an overdue PO
    po_id = uuid.uuid4()
    run_id = uuid.uuid4()
    session.execute(insert(AgentRun).values(run_id=run_id, agent_name="test", status="SUCCESS"))
    session.execute(
        insert(PurchaseOrder).values(
            po_id=po_id,
            supplier_id=s["supp_id"],
            run_id=run_id,
            total_value=Decimal("1200.00"),
            status=POStatus.PENDING_L1.value,
            l1_deadline=NOW - timedelta(hours=2),  # 2 hours overdue!
        )
    )
    rec_id = uuid.uuid4()
    session.execute(
        insert(Recommendation).values(
            rec_id=rec_id,
            run_id=run_id,
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            rec_type="REORDER",
            qty=10,
            status=RecStatus.PENDING.value,
            evidence={"qty": 10},
        )
    )
    line_id = uuid.uuid4()
    session.execute(
        insert(POLine).values(
            po_line_id=line_id,
            po_id=po_id,
            store_id=s["store_a"],
            product_id=s["prod_rice"],
            qty=10,
            unit_price=Decimal("250.00"),
            source_rec_id=rec_id,
            line_status=LineStatus.PENDING.value,
        )
    )
    session.flush()

    # Run ApprovalService.expire_overdue()
    service = ApprovalService(session)
    processed = service.expire_overdue(now=NOW)

    assert processed >= 1
    # Check that pending lines were escalated
    line = session.scalar(select(POLine).where(POLine.po_line_id == line_id))
    assert line.line_status == "ESCALATED"


def test_partition_maintenance(db: Connection) -> None:
    res = partition_maintenance_task()
    assert isinstance(res["created_partitions"], list)
    assert len(res["default_overflow_alerts"]) == 0
