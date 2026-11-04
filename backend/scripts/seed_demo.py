"""Seed rich demo state representing all five demo scenarios (spec Phase 9).

Usage:
    cd backend && uv run python -m scripts.seed_demo
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_async_session_factory, get_sync_engine, use_selector_event_loop
from app.domain.models import (
    AgentRun,
    Batch,
    InventoryPosition,
    LLMUsage,
    Notification,
    POLine,
    Product,
    PurchaseOrder,
    Recommendation,
    Store,
    Supplier,
    ToolCall,
    TransferOrder,
)
from app.domain.models.enums import (
    LineStatus,
    POStatus,
    Priority,
    RecStatus,
    RecType,
    ToolCallStatus,
    TransferStatus,
)
from scripts.seed import seed, seed_password


async def seed_demo_data() -> None:
    print("[SEED] Seeding RetailPilot AI interactive demo environment...")

    # 1. Ensure master stores & users exist
    settings = get_settings()
    engine = get_sync_engine()
    pwd = seed_password(settings)
    seed_res = seed(engine, pwd)
    print(
        f"[OK] Master data ready (stores created: {seed_res.stores_created}, users created: {seed_res.users_created})"
    )

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        # Load stores
        stores_res = await session.execute(select(Store).order_by(Store.code))
        stores = {s.code: s for s in stores_res.scalars().all()}
        if len(stores) < 3:
            print("[ERROR] Stores not found in database. Please run alembic migrations first.")
            return

        ordered = list(stores.values())
        store_a = stores.get("BLR-KOR") or ordered[0]
        store_b = stores.get("BLR-IND") or ordered[1]
        store_c = stores.get("BLR-HSR") or ordered[2]

        # Ensure demo products exist
        prod_res = await session.execute(select(Product).limit(10))
        products = list(prod_res.scalars().all())
        if not products:
            milk = Product(
                product_id=uuid.uuid4(),
                sku="DAI-MILK-TONED-1L",
                name="Fresh Toned Milk 1L",
                category="Dairy & Eggs",
                brand="Nandini",
                shelf_life_days=3,
                cost_price=Decimal("42.00"),
                selling_price=Decimal("54.00"),
                pack_size=1,
            )
            bread = Product(
                product_id=uuid.uuid4(),
                sku="BAK-BREAD-WHITE-400G",
                name="Premium White Bread 400g",
                category="Bakery",
                brand="Modern",
                shelf_life_days=5,
                cost_price=Decimal("28.00"),
                selling_price=Decimal("40.00"),
                pack_size=1,
            )
            paneer = Product(
                product_id=uuid.uuid4(),
                sku="DAI-PANEER-MALAI-200G",
                name="Malai Paneer Fresh 200g",
                category="Dairy & Eggs",
                brand="MilkyMist",
                shelf_life_days=14,
                cost_price=Decimal("75.00"),
                selling_price=Decimal("110.00"),
                pack_size=1,
            )
            session.add_all([milk, bread, paneer])
            await session.flush()
            products = [milk, bread, paneer]

        prod_milk = products[0]
        prod_bread = products[1] if len(products) > 1 else products[0]
        prod_paneer = products[2] if len(products) > 2 else products[0]

        # Ensure demo supplier exists
        supp_res = await session.execute(select(Supplier).limit(1))
        supplier = supp_res.scalar_one_or_none()
        if not supplier:
            supplier = Supplier(
                supplier_id=uuid.uuid4(),
                name="Amrit Dairy & Provisions Co.",
                default_lead_time_days=1,
                is_active=True,
            )
            session.add(supplier)
            await session.flush()

        now = datetime.now(UTC)
        today = now.date()

        # 2. Seed Initial Inventory Positions (on conflict do nothing)
        pos_a = InventoryPosition(
            store_id=store_a.store_id,
            product_id=prod_milk.product_id,
            shelf_qty=4,
            backroom_qty=2,
            reserved=0,
            incoming=0,
            in_transit_out=0,
        )
        pos_b = InventoryPosition(
            store_id=store_b.store_id,
            product_id=prod_paneer.product_id,
            shelf_qty=45,
            backroom_qty=30,
            reserved=0,
            incoming=0,
            in_transit_out=0,
        )
        pos_c = InventoryPosition(
            store_id=store_c.store_id,
            product_id=prod_paneer.product_id,
            shelf_qty=2,
            backroom_qty=0,
            reserved=0,
            incoming=0,
            in_transit_out=0,
        )
        for p in [pos_a, pos_b, pos_c]:
            await session.merge(p)

        # Near-expiry batch for Scenario 5
        batch_id = uuid.uuid4()
        batch_paneer = Batch(
            batch_id=batch_id,
            store_id=store_b.store_id,
            product_id=prod_paneer.product_id,
            batch_no="LOT-PNR-202611-01",
            qty=18,
            received_date=today - timedelta(days=12),
            expiry_date=today + timedelta(days=2),
        )
        session.add(batch_paneer)

        # 3. Seed Root Agent Run & Telemetry for Monitoring
        root_run_id = uuid.uuid4()
        root_run = AgentRun(
            run_id=root_run_id,
            agent_name="nightly_replenishment",
            status="SUCCESS",
            started_at=now - timedelta(minutes=45),
            ended_at=now - timedelta(minutes=42),
            run_date=today,
            input_ref={"stores": 3, "skus": len(products), "date": str(today)},
            output_summary="Nightly autonomous pipeline evaluated all stores. Generated 4 replenishment recommendations and 1 inter-store transfer proposal.",
        )
        session.add(root_run)

        # Child agent run: SalesAnalyticsAgent
        sales_run_id = uuid.uuid4()
        sales_run = AgentRun(
            run_id=sales_run_id,
            parent_run_id=root_run_id,
            agent_name="SalesAnalyticsAgent",
            status="SUCCESS",
            started_at=now - timedelta(minutes=45),
            ended_at=now - timedelta(minutes=44),
            run_date=today,
            input_ref={"period": "LAST_28_DAYS"},
            output_summary="Processed 28 days of POS transactions. Detected +34% sales surge in Fresh Dairy categories.",
        )
        session.add(sales_run)

        # Telemetry Tool Calls
        tc1 = ToolCall(
            call_id=uuid.uuid4(),
            run_id=sales_run_id,
            tool_name="query_velocity_metrics",
            args={"category": "Dairy & Eggs", "days": 28},
            result_summary="Scanned 1420 POS rows. Peak velocity SKU: DAI-MILK-TONED-1L",
            status=ToolCallStatus.OK.value,
            duration_ms=142,
            created_at=now - timedelta(minutes=44, seconds=45),
        )
        session.add(tc1)

        # LLM Token Usage
        llm1 = LLMUsage(
            usage_id=uuid.uuid4(),
            run_id=root_run_id,
            provider="anthropic",
            model="claude-3-7-sonnet-20250219",
            input_tokens=1840,
            output_tokens=395,
            est_cost=Decimal("0.005820"),
            created_at=now - timedelta(minutes=43),
        )
        session.add(llm1)

        # 4. Scenario 1: Urgent Stockout Replenishment (Store A Milk)
        rec1_id = uuid.uuid4()
        rec1 = Recommendation(
            rec_id=rec1_id,
            run_id=root_run_id,
            store_id=store_a.store_id,
            product_id=prod_milk.product_id,
            rec_type=RecType.REORDER.value,
            priority=Priority.HIGH.value,
            qty=36,
            reason="CRITICAL_STOCKOUT",
            status=RecStatus.PENDING.value,
            lost_sales_value=Decimal("1728.00"),
            lost_profit=Decimal("432.00"),
            explanation="Critical stockout imminent in Koramangala. On-hand stock is 6 units against a forecasted daily consumption of 38 units. Supplier lead time is 1 day.",
            evidence={
                "daily_velocity": 38.0,
                "days_of_supply": 0.2,
                "supplier_name": supplier.name,
                "lead_time_days": 1,
                "service_level_target": 0.98,
            },
            created_at=now,
        )
        session.add(rec1)

        # 5. Scenario 2: Consolidated PO Pending L2 Super Admin Approval
        po_id = uuid.uuid4()
        deadline_l1 = now + timedelta(hours=3, minutes=30)
        po = PurchaseOrder(
            po_id=po_id,
            supplier_id=supplier.supplier_id,
            run_id=root_run_id,
            total_value=Decimal("56400.00"),
            required_level="L2",
            status=POStatus.PENDING_L2.value,
            l1_deadline=deadline_l1,
            created_at=now - timedelta(hours=1),
        )
        session.add(po)

        po_ln1 = POLine(
            po_line_id=uuid.uuid4(),
            po_id=po_id,
            product_id=prod_milk.product_id,
            store_id=store_a.store_id,
            qty=480,
            unit_price=prod_milk.cost_price,
            source_rec_id=rec1_id,
            line_status=LineStatus.APPROVED.value,
        )
        po_ln2 = POLine(
            po_line_id=uuid.uuid4(),
            po_id=po_id,
            product_id=prod_paneer.product_id,
            store_id=store_b.store_id,
            qty=350,
            unit_price=prod_paneer.cost_price,
            source_rec_id=rec1_id,
            line_status=LineStatus.PENDING.value,
        )
        session.add_all([po_ln1, po_ln2])

        # 6. Scenario 3: Expiry-Aware Inter-Store Transfer (Store B -> Store C Paneer)
        rec3_id = uuid.uuid4()
        rec3 = Recommendation(
            rec_id=rec3_id,
            run_id=root_run_id,
            store_id=store_c.store_id,
            product_id=prod_paneer.product_id,
            rec_type=RecType.TRANSFER.value,
            priority=Priority.NORMAL.value,
            qty=20,
            reason="INTER_STORE_SURPLUS",
            status=RecStatus.ACCEPTED.value,
            lost_sales_value=Decimal("0.00"),
            lost_profit=Decimal("0.00"),
            explanation="Store B has surplus stock with 10 days shelf life. Store C faces shortage. Rebalancing from Store B preserves Store B requirements and saves procurement lead time.",
            evidence={
                "from_store": store_b.name,
                "transit_days": 1,
                "donor_kept_requirement": True,
            },
            created_at=now - timedelta(minutes=35),
        )
        session.add(rec3)

        transfer_id = uuid.uuid4()
        transfer = TransferOrder(
            transfer_id=transfer_id,
            from_store_id=store_b.store_id,
            to_store_id=store_c.store_id,
            product_id=prod_paneer.product_id,
            batch_id=batch_id,
            qty=20,
            transfer_cost=Decimal("120.00"),
            transit_days=1,
            is_expiry_aware=True,
            source_rec_id=rec3_id,
            status=TransferStatus.PROPOSED.value,
            created_at=now - timedelta(minutes=30),
        )
        session.add(transfer)

        # 7. Scenario 4: Association Rule Co-Replenishment (Bread reorder linked to Milk)
        rec4_id = uuid.uuid4()
        rec4 = Recommendation(
            rec_id=rec4_id,
            run_id=root_run_id,
            store_id=store_a.store_id,
            product_id=prod_bread.product_id,
            rec_type=RecType.REORDER.value,
            priority=Priority.NORMAL.value,
            qty=24,
            reason="ASSOCIATION_RULE",
            status=RecStatus.PENDING.value,
            lost_sales_value=Decimal("640.00"),
            lost_profit=Decimal("192.00"),
            explanation="Co-replenishment triggered: 42% of customer baskets containing Fresh Toned Milk also purchase Premium White Bread (Lift 2.4). Reorder adjusted to meet joint demand surge.",
            evidence={
                "rule_name": "Milk_Bread_CoPurchase",
                "antecedent_sku": prod_milk.sku,
                "confidence": 0.42,
                "lift": 2.4,
                "adjusted_demand_lift": "+18%",
            },
            created_at=now,
        )
        session.add(rec4)

        # 8. Scenario 5: Imminent Expiry Markdown & Alert
        rec5_id = uuid.uuid4()
        rec5 = Recommendation(
            rec_id=rec5_id,
            run_id=root_run_id,
            store_id=store_b.store_id,
            product_id=prod_paneer.product_id,
            rec_type=RecType.TRANSFER.value,
            priority=Priority.HIGH.value,
            qty=18,
            reason="NEAR_EXPIRY",
            status=RecStatus.PENDING.value,
            lost_sales_value=Decimal("1980.00"),
            lost_profit=Decimal("630.00"),
            explanation="Batch LOT-PNR-202611-01 (18 units) expires in 2 days. Store B demand cannot absorb this before expiration; urgent FIFO dispatch or 25% discount markdown recommended.",
            evidence={
                "batch_no": "LOT-PNR-202611-01",
                "days_until_expiry": 2,
                "risk_of_spoilage_value": 1980.0,
                "action": "TRANSFER_TO_HIGH_VELOCITY_OUTLET",
            },
            created_at=now,
        )
        session.add(rec5)

        # 9. Live demo notification
        notif = Notification(
            notification_id=uuid.uuid4(),
            user_id=None,
            role="SUPER_ADMIN",
            store_id=None,
            message="PO exceeds Rs. 50,000 threshold (Rs. 56,400.00). Pending L2 Super Admin sign-off.",
            link="/approvals",
            read_at=None,
            created_at=now,
        )
        session.add(notif)

        await session.commit()
        print("[SUCCESS] All 5 demonstration scenarios successfully seeded:")
        print("  1. Scenario 1: Urgent Milk Stockout Replenishment (Store A)")
        print("  2. Scenario 2: High-Value Consolidated PO Pending L2 Approval")
        print("  3. Scenario 3: Expiry-Aware Inter-Store Balancing Transfer (Store B -> Store C)")
        print("  4. Scenario 4: Basket Association Rule Co-Replenishment (Milk + Bread)")
        print("  5. Scenario 5: Imminent Expiry Freshness Alert & Markdown Protection")


if __name__ == "__main__":
    use_selector_event_loop()
    asyncio.run(seed_demo_data())
