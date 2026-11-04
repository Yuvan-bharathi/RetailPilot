"""Record EXPLAIN (ANALYZE, BUFFERS) query execution plans for top-10 queries (D-38, spec §11).

Usage (from backend/):
    uv run python -m scripts.record_query_plans
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from app.core.db import worker_session
from app.domain.models.master import Store

DOC_TARGET = Path(__file__).resolve().parents[2] / "docs" / "notes" / "query-plans.md"

QUERIES: list[tuple[str, str, dict[str, object]]] = [
    (
        "1. Recommendation Inbox (Pending, Ranked)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT rec_id, store_id, product_id, rec_type, priority_rank, status, created_at
        FROM recommendation
        WHERE store_id = :store_id AND status = 'PENDING'
        ORDER BY priority_rank ASC, created_at DESC
        LIMIT 50;
        """,
        {},
    ),
    (
        "2. L1 PO Review Queue (Pending Lines for Store)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT po_line_id, po_id, store_id, product_id, line_status, qty, unit_price
        FROM po_line
        WHERE store_id = :store_id AND line_status = 'PENDING';
        """,
        {},
    ),
    (
        "3. PO Approval Deadline Job (Overdue L1 Orders)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT po_id, parent_po_id, status, l1_deadline, total_value
        FROM purchase_order
        WHERE status = 'PENDING_L1' AND l1_deadline <= :now;
        """,
        {"now": datetime.now(UTC)},
    ),
    (
        "4. Active Outbound Transfers (Donor Store Queue)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT transfer_id, from_store_id, to_store_id, product_id, qty, status
        FROM transfer_order
        WHERE from_store_id = :store_id
          AND status IN ('PROPOSED', 'DEST_ACCEPTED', 'APPROVED_RELEASE', 'DISPATCHED');
        """,
        {},
    ),
    (
        "5. Active Inbound Transfers (Destination Store Queue)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT transfer_id, from_store_id, to_store_id, product_id, qty, status
        FROM transfer_order
        WHERE to_store_id = :store_id
          AND status IN ('PROPOSED', 'DEST_ACCEPTED', 'APPROVED_RELEASE', 'DISPATCHED');
        """,
        {},
    ),
    (
        "6. Stock Movements Tab (Keyset Keyset-Cursor Paging, D-37)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT movement_id, store_id, product_id, occurred_at, movement_type, qty, location
        FROM inventory_movement
        WHERE store_id = :store_id
          AND (occurred_at, movement_id) < (:occurred_at, :movement_id)
        ORDER BY occurred_at DESC, movement_id DESC
        LIMIT 50;
        """,
        {"occurred_at": datetime.now(UTC), "movement_id": uuid.uuid4()},
    ),
    (
        "7. Per-Product Ledger History",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT movement_id, store_id, product_id, occurred_at, movement_type, qty, location
        FROM inventory_movement
        WHERE store_id = :store_id AND product_id = :product_id
        ORDER BY occurred_at DESC
        LIMIT 50;
        """,
        {"product_id": uuid.uuid4()},
    ),
    (
        "8. Store Inventory Positions (Active Stock by Product)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT store_id, product_id, shelf_qty, backroom_qty, reserved, incoming
        FROM inventory_position
        WHERE store_id = :store_id
        ORDER BY product_id
        LIMIT 50;
        """,
        {},
    ),
    (
        "9. Freshness Scan (Expiring Batches with Stock, D-38)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT batch_id, store_id, product_id, batch_no, qty, expiry_date
        FROM batch
        WHERE store_id = :store_id AND qty > 0
        ORDER BY expiry_date ASC
        LIMIT 50;
        """,
        {},
    ),
    (
        "10. Sales Aggregate for Demand Window (Daily Baseline Ingestion)",
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT product_id, SUM(qty) AS total_sold
        FROM sales_line
        WHERE store_id = :store_id
          AND txn_date >= :start_date
          AND is_voided = FALSE
          AND is_return = FALSE
        GROUP BY product_id;
        """,
        {"start_date": date.today() - timedelta(days=30)},
    ),
]


def run_plans() -> str:
    lines: list[str] = [
        "# Top-10 Query Execution Plans (D-38, spec §11)",
        "",
        f"Recorded on: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "Database: PostgreSQL 16 (retailpilot)",
        "",
        "Plans generated using `EXPLAIN (ANALYZE, BUFFERS)` to verify index usage",
        "and ensure no unindexed sequential scans occur on high-cardinality tables.",
        "",
        "---",
        "",
    ]

    with worker_session() as sess:
        store = sess.scalars(select(Store)).first()
        store_id = store.store_id if store else uuid.uuid4()

        for title, sql, params in QUERIES:
            lines.append(f"## {title}")
            lines.append("")
            lines.append("```sql")
            lines.append(sql.strip())
            lines.append("```")
            lines.append("")
            lines.append("```text")

            exec_params = {"store_id": store_id} | params
            result = sess.execute(text(sql), exec_params).fetchall()
            for row in result:
                lines.append(str(row[0]))

            lines.append("```")
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    output = run_plans()
    DOC_TARGET.parent.mkdir(parents=True, exist_ok=True)
    DOC_TARGET.write_text(output, encoding="utf-8")
    print(f"Recorded top-10 query plans in {DOC_TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
