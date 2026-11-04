"""Related Product Agent (SD-05, spec §8, decision D-22).

Mines cross-store basket association rules (complements and substitutes) using FP-Growth,
and detects assortment gaps across store listings.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pandas as pd
from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.master import StoreProduct
from app.domain.models.planning import AssociationRule, Recommendation
from app.domain.models.sales import SalesLine
from app.domain.repositories.planning_repo import PlanningRepo
from app.tools.basket import BasketTools


class RelatedProductAgent(BaseAgent):
    name = "RelatedProductAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        lookback_start = ctx.run_date - timedelta(days=90)
        total_rules = 0
        rules_by_store: dict[UUID, pd.DataFrame] = {}

        # 1. Fetch recent clean sales transactions per store
        for store_id in ctx.store_ids:
            stmt = (
                select(SalesLine.bill_id, SalesLine.product_id)
                .where(
                    SalesLine.store_id == store_id,
                    SalesLine.txn_date >= lookback_start,
                )
            )
            rows = ctx.session.execute(stmt).all()
            if not rows:
                continue

            df = pd.DataFrame([{"bill_id": r.bill_id, "product_id": r.product_id} for r in rows])
            n_bills = df["bill_id"].nunique()
            if n_bills < 10:  # minimum bills threshold
                continue

            # Convert to basket matrix and mine rules
            basket_mat = BasketTools.to_basket_matrix(df)
            rules_df = BasketTools.mine_rules(
                basket_mat, min_support=0.005, min_confidence=0.1, min_lift=1.0
            )
            if rules_df.empty:
                continue

            rules_by_store[store_id] = rules_df

            rule_models: list[AssociationRule] = []
            for r in rules_df.itertuples():
                rule_models.append(
                    AssociationRule(
                        rule_id=uuid.uuid4(),
                        run_id=ctx.run_id,
                        store_id=store_id,
                        antecedent_id=r.antecedent_id,
                        consequent_id=r.consequent_id,
                        support=float(cast(Any, r.support)),
                        confidence=float(cast(Any, r.confidence)),
                        lift=float(cast(Any, r.lift)),
                        rule_type="COMPLEMENT",
                    )
                )
            planning_repo.replace_association_rules(ctx.run_id, store_id, rule_models)
            total_rules += len(rule_models)

        # 2. Assortment gap detection
        all_store_products = ctx.session.scalars(select(StoreProduct)).all()
        listings_df = pd.DataFrame([
            {
                "store_id": sp.store_id,
                "product_id": sp.product_id,
                "is_listed": sp.is_listed,
            }
            for sp in all_store_products
        ])

        total_gaps = 0
        if not listings_df.empty and rules_by_store:
            gaps = BasketTools.find_assortment_gaps(rules_by_store, listings_df)
            gap_recs: list[Recommendation] = []
            for g in gaps:
                gap_recs.append(
                    Recommendation(
                        rec_id=uuid.uuid4(),
                        run_id=ctx.run_id,
                        store_id=g.store_id,
                        product_id=g.product_id,
                        rec_type="ASSORTMENT_GAP",
                        qty=0,
                        priority="NORMAL",
                        evidence=dict(g.evidence),
                        status="PENDING",
                    )
                )
            if gap_recs:
                planning_repo.insert_recommendations(gap_recs)
                total_gaps = len(gap_recs)

        return AgentResult(
            status="SUCCESS",
            outputs={"rules": total_rules, "gaps": total_gaps},
            step_count=3,
        )
