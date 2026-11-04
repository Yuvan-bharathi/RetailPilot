"""Celery background tasks (spec §7, SD-01, SD-14, D-35).

Tasks:
1. nightly_run_task: Executes end-to-end replenishment pipeline
2. approval_deadline_task: Escalates or expires overdue PENDING_L1 PO lines
3. partition_maintenance_task: Creates future monthly table partitions and checks for default partition overflow
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from celery import shared_task
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.orchestrator import WorkflowOrchestrator
from app.core.db import get_sync_engine
from app.services.approval_service import ApprovalService

logger = logging.getLogger(__name__)


@shared_task(name="nightly_run_task")
def nightly_run_task(run_date_str: str | None = None) -> dict[str, Any]:
    run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date() if run_date_str else date.today()
    engine = get_sync_engine()
    with Session(engine) as session:
        orchestrator = WorkflowOrchestrator(session)
        summary = orchestrator.run_nightly(run_date=run_date)
        return {
            "run_id": str(summary.run_id),
            "status": summary.status,
            "recommendations": summary.recommendations_count,
            "purchase_orders": summary.po_count,
            "transfers": summary.transfers_count,
            "duration_s": summary.duration_s,
            "error": summary.error,
        }


@shared_task(name="approval_deadline_task")
def approval_deadline_task() -> dict[str, Any]:
    engine = get_sync_engine()
    with Session(engine) as session, session.begin():
        service = ApprovalService(session)
        processed = service.expire_overdue()
        return {"overdue_pos_processed": processed}


@shared_task(name="partition_maintenance_task")
def partition_maintenance_task() -> dict[str, Any]:
    """Creates future monthly partitions for sales_line and inventory_movement,

    and raises alerts if default partitions contain rows (D-35).
    """
    engine = get_sync_engine()
    created_partitions: list[str] = []
    default_overflow_alerts: list[str] = []

    with Session(engine) as session, session.begin():
        # 1. Check for overflow in default partitions
        for table in ("sales_line", "inventory_movement"):
            count = session.scalar(text(f"SELECT COUNT(*) FROM {table}_default")) or 0
            if count > 0:
                alert = f"CRITICAL: {table}_default contains {count} unpartitioned rows!"
                logger.error(alert)
                default_overflow_alerts.append(alert)

        # 2. Pre-create next 3 monthly partitions
        today = date.today()
        for month_offset in range(0, 4):
            # Calculate target year and month
            target_year = today.year + (today.month + month_offset - 1) // 12
            target_month = (today.month + month_offset - 1) % 12 + 1
            suffix = f"{target_year}_{target_month:02d}"

            start_date = date(target_year, target_month, 1)
            if target_month == 12:
                end_date = date(target_year + 1, 1, 1)
            else:
                end_date = date(target_year, target_month + 1, 1)

            for table in ("sales_line", "inventory_movement"):
                part_name = f"{table}_{suffix}"
                exists = session.scalar(text(f"SELECT to_regclass('{part_name}')"))
                if not exists:
                    ddl = (
                        f"CREATE TABLE IF NOT EXISTS {part_name} "
                        f"PARTITION OF {table} FOR VALUES FROM ('{start_date}') TO ('{end_date}')"
                    )
                    session.execute(text(ddl))
                    created_partitions.append(part_name)
                    logger.info("Created partition %s", part_name)

    return {
        "created_partitions": created_partitions,
        "default_overflow_alerts": default_overflow_alerts,
    }
