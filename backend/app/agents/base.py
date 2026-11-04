"""Base agent interface, RunContext, and AgentResult (SD-01, spec §8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.repositories.observability_repo import AgentRunLogger


@dataclass
class RunParams:
    kpi_lookback_days: int = 28
    forecast_horizon_days: int = 14
    forecast_lookback_days: int = 180
    min_history_days: int = 56
    incoming_overdue_grace_days: int = 3
    expiry_window_days: int = 14
    max_steps: int = 50
    stale_days: int = 30
    markdown_enabled: bool = False
    schemes_enabled: bool = False
    use_model_selection: bool = (
        False  # D-45: off — the replay showed no gain over the baseline on current data
    )
    use_calendar_uplift: bool = False

    @classmethod
    def load(cls, session: Session | None = None) -> RunParams:
        # Default parameters from business rules or dataclass defaults
        return cls()


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
