"""BusinessRule defaults (spec §9, D-35).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04

Global rows (scope_store_id NULL), one per key. Values are copied here as literals so this migration never changes
when application code changes; `tests/unit/test_models.py` asserts they equal the synthetic dataset's
`BUSINESS_RULES` (the values the tools are tested with). Money and rates are JSON strings so they load as exact
`Decimal`s. Re-running is harmless: ON CONFLICT (rule_key, scope_store_id) DO NOTHING.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_RULES: dict[str, Any] = {
    "po_l2_threshold": "50000",
    "weekly_budget": "500000",
    "order_fixed_cost": "250",
    "holding_cost_rate_per_day": "0.0005",
    "expiry_risk_pct": "0.10",
    "perishable_max_shelf_life_days": 30,
    "days_to_sell_default_cap": 90,
    "incoming_overdue_grace_days": 3,
    "l1_deadline_hours": 24,
    "deadline_action": "ESCALATE",
    "stale_days": 3,
    "kpi_lookback_days": 28,
    "expiry_window_days": 14,
    "max_steps": 50,
    "basket": {
        "min_bills": 500,
        "min_support": 0.005,
        "min_confidence": 0.2,
        "min_lift": 1.0,
        "max_qty_per_line": 24,
        "max_qty_per_line_by_category": {},
        "exclude_promo_days": True,
    },
    "co_replenish": {"min_lift": 1.5, "limit": 3},
}

_INSERT = sa.text(
    "INSERT INTO business_rule (rule_key, value, scope_store_id) "
    "VALUES (:key, CAST(:value AS jsonb), NULL) "
    "ON CONFLICT (rule_key, scope_store_id) DO NOTHING"
)


def upgrade() -> None:
    bind = op.get_bind()
    for key, value in DEFAULT_RULES.items():
        bind.execute(_INSERT, {"key": key, "value": json.dumps(value)})


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM business_rule WHERE scope_store_id IS NULL AND rule_key = ANY(:keys)"),
        {"keys": list(DEFAULT_RULES)},
    )
