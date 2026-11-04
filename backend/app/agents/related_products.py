"""Related Product Agent (SD-05, spec §8; D-22, D-27, D-34, D-47).

Per store, over the last 90 days: clean the bills (returns, voided lines, whole bulk bills above the per-category
line limit, promotion days — business rules `basket.*`), skip the store below `basket.min_bills`, mine
association rules with FP-Growth at the configured support / confidence / lift, and store them for this run.
Assortment gaps: a strong rule X→Y in other stores suggests Y to a store that lists X but not Y (one
recommendation per store-product, D-34 AssortmentGapEvidence).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pandas as pd
from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.domain.models.master import Product, Store, StoreProduct
from app.domain.models.observability import DecisionEvidence
from app.domain.models.planning import AssociationRule, Recommendation
from app.domain.models.sales import SalesLine
from app.domain.repositories.planning_repo import PlanningRepo
from app.domain.schemas.common import ProductRef, StoreRef
from app.domain.schemas.dtos import AssortmentGapEvidence
from app.tools.basket import BasketTools
from app.tools.types import BasketQualityRules

LOOKBACK_DAYS = 90


class RelatedProductAgent(BaseAgent):
    name = "RelatedProductAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        planning_repo = PlanningRepo(ctx.session)
        basket = ctx.params.basket
        quality = BasketQualityRules(
            max_qty_per_line=int(basket["max_qty_per_line"]),
            exclude_promo_days=bool(basket["exclude_promo_days"]),
            max_qty_per_line_by_category=dict(basket.get("max_qty_per_line_by_category") or {}),
        )
        lookback_start = ctx.run_date - timedelta(days=LOOKBACK_DAYS)
        total_rules = 0
        skipped: list[str] = []
        rules_by_store: dict[UUID, pd.DataFrame] = {}

        for store_id in ctx.store_ids:
            rows = ctx.session.execute(
                select(
                    SalesLine.bill_id,
                    SalesLine.product_id,
                    SalesLine.qty,
                    SalesLine.is_return,
                    SalesLine.is_voided,
                    SalesLine.is_promo_day,
                    Product.category,
                )
                .join(Product, Product.product_id == SalesLine.product_id)
                .where(
                    SalesLine.store_id == store_id,
                    SalesLine.txn_date >= lookback_start,
                    SalesLine.txn_date < ctx.run_date,
                )
            ).all()
            lines = pd.DataFrame(
                rows,
                columns=[
                    "bill_id",
                    "product_id",
                    "qty",
                    "is_return",
                    "is_voided",
                    "is_promo_day",
                    "category",
                ],
            )
            cleaned = BasketTools.clean_bills(lines, quality) if not lines.empty else lines
            if cleaned.empty or cleaned["bill_id"].nunique() < int(basket["min_bills"]):
                skipped.append(str(store_id))  # SD-05: too few bills, skipped and logged
                continue
            rules_df = BasketTools.mine_rules(
                BasketTools.to_basket_matrix(cleaned),
                min_support=float(basket["min_support"]),
                min_confidence=float(basket["min_confidence"]),
                min_lift=float(basket["min_lift"]),
            )
            if rules_df.empty:
                continue
            rules_by_store[store_id] = rules_df
            models = [
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
                for r in rules_df.itertuples()
            ]
            planning_repo.replace_association_rules(ctx.run_id, store_id, models)
            total_rules += len(models)

        gaps = self._assortment_gaps(ctx, rules_by_store, planning_repo)
        ctx.logger.log_tool_call(
            ctx.run_id,
            "mine_rules",
            {"stores": len(ctx.store_ids), "min_bills": int(basket["min_bills"])},
            f"{total_rules} rules, {gaps} gaps, skipped stores: {skipped or 'none'}",
            0,
            "WARN" if skipped else "OK",
        )
        return AgentResult(
            status="SUCCESS", outputs={"rules": total_rules, "gaps": gaps, "skipped_stores": len(skipped)}
        )

    @staticmethod
    def _assortment_gaps(
        ctx: RunContext, rules_by_store: dict[UUID, pd.DataFrame], planning_repo: PlanningRepo
    ) -> int:
        if not rules_by_store:
            return 0
        listings = pd.DataFrame(
            [(sp.store_id, sp.product_id, sp.is_listed) for sp in ctx.session.scalars(select(StoreProduct))],
            columns=["store_id", "product_id", "is_listed"],
        )
        if listings.empty:
            return 0
        products = {p.product_id: p for p in ctx.session.scalars(select(Product))}
        stores = {s.store_id: s for s in ctx.session.scalars(select(Store))}
        recs: list[Recommendation] = []
        for gap in BasketTools.find_assortment_gaps(
            rules_by_store, listings, min_lift=float(ctx.params.co_replenish["min_lift"])
        ):
            antecedent = products[UUID(str(gap.evidence["antecedent_id"]))]
            sources = [UUID(str(s)) for s in cast(list[str], gap.evidence["source_stores"])]
            data = AssortmentGapEvidence(
                kind="ASSORTMENT_GAP",
                antecedent=ProductRef(
                    product_id=antecedent.product_id,
                    sku=antecedent.sku,
                    name=antecedent.name,
                    category=antecedent.category,
                ),
                lift=round(float(cast(Any, gap.evidence["lift"])), 2),
                source_stores=[StoreRef(store_id=s, name=stores[s].name) for s in sources if s in stores],
            ).model_dump(mode="json")
            rec_id = uuid.uuid4()
            recs.append(
                Recommendation(
                    rec_id=rec_id,
                    run_id=ctx.run_id,
                    store_id=gap.store_id,
                    product_id=gap.product_id,
                    rec_type="ASSORTMENT_GAP",
                    qty=0,
                    priority="NORMAL",
                    reason="ASSORTMENT_GAP",
                    evidence=data,
                    status="PENDING",
                )
            )
            ctx.session.add(
                DecisionEvidence(run_id=ctx.run_id, rec_id=rec_id, data=data, validation_result="VALID")
            )
        if recs:
            planning_repo.insert_recommendations(recs)
        return len(recs)
