"""Planning repository: forecasts, recommendations, replenishment needs, rules, and KPIs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.domain.models.planning import (
    AssociationRule,
    Forecast,
    KpiSnapshot,
    LostSalesEstimate,
    Recommendation,
    ReplenishmentNeed,
)


class PlanningRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_kpis(self, run_id: UUID, kpis: list[KpiSnapshot]) -> int:
        if not kpis:
            return 0
        for k in kpis:
            self.session.add(k)
        self.session.flush()
        return len(kpis)

    def save_lost_sales(self, run_id: UUID, rows: list[LostSalesEstimate]) -> int:
        if not rows:
            return 0
        for r in rows:
            self.session.add(r)
        self.session.flush()
        return len(rows)

    def bulk_insert_forecasts(self, run_id: UUID, forecasts: list[Forecast]) -> int:
        if not forecasts:
            return 0
        for f in forecasts:
            self.session.add(f)
        self.session.flush()
        return len(forecasts)

    def get_forecasts_by_run(self, run_id: UUID) -> dict[tuple[UUID, UUID], Forecast]:
        stmt = select(Forecast).where(Forecast.run_id == run_id)
        rows = self.session.scalars(stmt).all()
        return {(f.store_id, f.product_id): f for f in rows}

    def replace_association_rules(
        self, run_id: UUID, store_id: UUID, rules: list[AssociationRule]
    ) -> int:
        stmt = delete(AssociationRule).where(
            AssociationRule.store_id == store_id, AssociationRule.run_id != run_id
        )
        self.session.execute(stmt)
        for r in rules:
            self.session.add(r)
        self.session.flush()
        return len(rules)

    def insert_recommendations(self, recs: list[Recommendation]) -> list[Recommendation]:
        if not recs:
            return []
        for r in recs:
            self.session.add(r)
        self.session.flush()
        return recs

    def insert_replenishment_needs(self, needs: list[ReplenishmentNeed]) -> list[ReplenishmentNeed]:
        if not needs:
            return []
        for n in needs:
            self.session.add(n)
        self.session.flush()
        return needs

    def get_needs_by_run(self, run_id: UUID) -> list[ReplenishmentNeed]:
        stmt = select(ReplenishmentNeed).where(ReplenishmentNeed.run_id == run_id)
        return list(self.session.scalars(stmt).all())

    def get_recs_by_run(self, run_id: UUID) -> list[Recommendation]:
        stmt = select(Recommendation).where(Recommendation.run_id == run_id)
        return list(self.session.scalars(stmt).all())

    def set_explanation(self, rec_id: UUID, explanation: str) -> None:
        stmt = (
            update(Recommendation)
            .where(Recommendation.rec_id == rec_id)
            .values(explanation=explanation)
        )
        self.session.execute(stmt)

