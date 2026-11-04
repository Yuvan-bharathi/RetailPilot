"""Base agent interface, RunContext, and AgentResult (SD-01, spec §8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.repositories.observability_repo import AgentRunLogger


@dataclass
class RunParams:
    """Run parameters (spec §9). Business values come from the BusinessRule table (global rows), never code;
    the defaults below are only used for keys missing from the table and equal migration 0002's seed."""

    kpi_lookback_days: int = 28
    forecast_horizon_days: int = 14
    forecast_lookback_days: int = 180
    min_history_days: int = 56
    incoming_overdue_grace_days: int = 3
    expiry_window_days: int = 14
    max_steps: int = 50
    stale_days: int = 3
    order_fixed_cost: Decimal = Decimal("250")
    holding_cost_rate_per_day: Decimal = Decimal("0.0005")
    expiry_risk_pct: Decimal = Decimal("0.10")
    perishable_max_shelf_life_days: int = 30
    days_to_sell_default_cap: int = 90
    basket: dict[str, Any] = field(
        default_factory=lambda: {
            "min_bills": 500,
            "min_support": 0.005,
            "min_confidence": 0.2,
            "min_lift": 1.0,
            "max_qty_per_line": 24,
            "max_qty_per_line_by_category": {},
            "exclude_promo_days": True,
        }
    )
    co_replenish: dict[str, Any] = field(default_factory=lambda: {"min_lift": 1.5, "limit": 3})
    markdown_enabled: bool = False
    schemes_enabled: bool = False
    use_model_selection: bool = (
        False  # D-45: off — the replay showed no gain over the baseline on current data
    )
    use_calendar_uplift: bool = False

    _INT_RULES = (
        "kpi_lookback_days",
        "incoming_overdue_grace_days",
        "expiry_window_days",
        "max_steps",
        "stale_days",
        "perishable_max_shelf_life_days",
        "days_to_sell_default_cap",
    )
    _DECIMAL_RULES = ("order_fixed_cost", "holding_cost_rate_per_day", "expiry_risk_pct")

    @classmethod
    def load(cls, session: Session | None = None) -> RunParams:
        """Defaults overridden by the global BusinessRule rows (D-47)."""
        params = cls()
        if session is None:
            return params
        from app.domain.models.transfers import BusinessRule  # local: models import agents' callers

        rules = {
            r.rule_key: r.value
            for r in session.scalars(select(BusinessRule).where(BusinessRule.scope_store_id.is_(None)))
        }
        for key in cls._INT_RULES:
            if key in rules:
                setattr(params, key, int(rules[key]))
        for key in cls._DECIMAL_RULES:
            if key in rules:
                setattr(params, key, Decimal(str(rules[key])))
        for key in ("basket", "co_replenish"):
            if isinstance(rules.get(key), dict):
                setattr(params, key, getattr(params, key) | rules[key])
        return params


@dataclass
class RunContext:
    run_id: UUID
    run_date: date
    store_ids: list[UUID]
    stale_skus: list[tuple[UUID, UUID]]
    params: RunParams
    logger: AgentRunLogger
    session: Session
    agent_run_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def with_run(self, child_run_id: UUID) -> RunContext:
        """Create a child execution context bound to child_run_id."""
        return RunContext(
            run_id=self.run_id,
            run_date=self.run_date,
            store_ids=self.store_ids,
            stale_skus=self.stale_skus,
            params=self.params,
            logger=self.logger,
            session=self.session,
            agent_run_id=child_run_id,
            extra=self.extra,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "run_date": str(self.run_date),
            "store_count": len(self.store_ids),
            "stale_skus_count": len(self.stale_skus),
        }


@dataclass
class AgentResult:
    status: str  # "SUCCESS" | "FAILED"
    outputs: dict[str, Any] = field(default_factory=dict)
    step_count: int = 0
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "step_count": self.step_count,
            "outputs": self.outputs,
            "error": self.error,
        }


class BaseAgent(ABC):
    name: str
    critical: bool  # True -> failure halts nightly run; False -> overall run becomes PARTIAL

    @abstractmethod
    def run(self, ctx: RunContext) -> AgentResult:
        """Execute agent workflow within given context."""
