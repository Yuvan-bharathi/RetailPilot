"""BasketTools — bill cleaning, association rules, substitutes, assortment gaps (SD-05, D-22).

Complements (bought together) and substitutes (sales rise when another product is out of stock) are separate
analyses with different inputs, stored separately (requirements §5.4).
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pandas as pd
from mlxtend.frequent_patterns import association_rules, fpgrowth

from app.tools.types import BasketQualityRules, GapSuggestion

RULE_COLUMNS = ["antecedent_id", "consequent_id", "support", "confidence", "lift"]
SUBSTITUTE_COLUMNS = ["store_id", "product_a", "product_b", "uplift"]


class BasketTools:
    @staticmethod
    def clean_bills(lines: pd.DataFrame, rules: BasketQualityRules) -> pd.DataFrame:
        """Drop return lines (is_return or qty < 0), voided lines, whole bills with a line above
        max_qty_per_line (bulk / wholesale), and promotion-day lines. Optional flag columns may be absent."""
        df = lines
        if rules.exclude_returns:
            is_return = df["qty"] < 0
            if "is_return" in df.columns:
                is_return = is_return | df["is_return"].astype(bool)
            df = df.loc[~is_return]
        if rules.exclude_voided and "is_voided" in df.columns:
            df = df.loc[~df["is_voided"].astype(bool)]
        bulk_bills = set(df.loc[df["qty"] > rules.max_qty_per_line, "bill_id"])
        df = df.loc[~df["bill_id"].isin(bulk_bills)]
        if rules.exclude_promo_days and "is_promo_day" in df.columns:
            df = df.loc[~df["is_promo_day"].astype(bool)]
        return df.reset_index(drop=True)

    @staticmethod
    def to_basket_matrix(lines: pd.DataFrame) -> pd.DataFrame:
        """Bills × products boolean matrix (True = product on the bill)."""
        counts = pd.crosstab(lines["bill_id"], lines["product_id"])
        return counts.gt(0)

    @staticmethod
    def mine_rules(
        basket: pd.DataFrame,
        min_support: float = 0.005,
        min_confidence: float = 0.2,
        min_lift: float = 1.0,
        max_len: int = 2,
    ) -> pd.DataFrame:
        """Single-item rules from mlxtend fpgrowth + association_rules; keeps lift > min_lift (strict, D-22)."""
        frequent = fpgrowth(basket, min_support=min_support, use_colnames=True, max_len=max_len)
        if frequent.empty or (frequent["itemsets"].map(len) > 1).sum() == 0:
            return pd.DataFrame(columns=RULE_COLUMNS)
        rules = association_rules(
            frequent, num_itemsets=len(basket), metric="confidence", min_threshold=min_confidence
        )
        rules = rules.loc[
            (rules["lift"] > min_lift)
            & (rules["antecedents"].map(len) == 1)
            & (rules["consequents"].map(len) == 1)
        ]
        out = pd.DataFrame(
            {
                "antecedent_id": [next(iter(a)) for a in rules["antecedents"]],
                "consequent_id": [next(iter(c)) for c in rules["consequents"]],
                "support": rules["support"].astype(float).to_numpy(),
                "confidence": rules["confidence"].astype(float).to_numpy(),
                "lift": rules["lift"].astype(float).to_numpy(),
            },
            columns=RULE_COLUMNS,
        )
        out["_order"] = -out["lift"]
        out = out.sort_values(["_order", "antecedent_id", "consequent_id"], kind="stable")
        return out.drop(columns="_order").reset_index(drop=True)

    @staticmethod
    def detect_substitutes(
        daily_sales: pd.DataFrame,
        stockout_days: pd.DataFrame,
        same_category_only: bool = True,
        uplift_threshold: float = 0.3,
        min_stockout_days: int = 3,
    ) -> pd.DataFrame:
        """B substitutes A when, on A's stockout days, B's mean units rise ≥ uplift_threshold above B's mean on
        A's in-stock days. A needs ≥ min_stockout_days stockout days.

        daily_sales: [store_id, product_id, day, units, category]; stockout_days: [store_id, product_id, day].
        """
        rows: list[dict[str, Any]] = []
        out_days_by_key: dict[tuple[Any, Any], set[Any]] = {}
        for row in stockout_days.itertuples():
            out_days_by_key.setdefault((row.store_id, row.product_id), set()).add(row.day)
        for (store_id, product_a), a_out_days in sorted(out_days_by_key.items()):
            if len(a_out_days) < min_stockout_days:
                continue
            store_sales = daily_sales.loc[daily_sales["store_id"] == store_id]
            category_a = store_sales.loc[store_sales["product_id"] == product_a, "category"].iloc[0]
            by_product: dict[Any, pd.DataFrame] = dict(iter(store_sales.groupby("product_id")))
            for product_b in sorted(by_product):
                b_sales = by_product[product_b]
                if product_b == product_a:
                    continue
                if same_category_only and b_sales["category"].iloc[0] != category_a:
                    continue
                on_a_out = b_sales["day"].isin(a_out_days)
                normal = float(b_sales.loc[~on_a_out, "units"].mean())
                during = float(b_sales.loc[on_a_out, "units"].mean())
                if not normal > 0:
                    continue
                uplift = (during - normal) / normal
                if uplift >= uplift_threshold:
                    rows.append(
                        {
                            "store_id": store_id,
                            "product_a": product_a,
                            "product_b": product_b,
                            "uplift": uplift,
                        }
                    )
        return pd.DataFrame(rows, columns=SUBSTITUTE_COLUMNS)

    @staticmethod
    def find_assortment_gaps(
        rules_by_store: Mapping[UUID, pd.DataFrame],
        listings: pd.DataFrame,
        min_lift: float = 1.5,
        min_stores: int = 1,
    ) -> list[GapSuggestion]:
        """A rule X→Y (lift ≥ min_lift) holding in ≥ min_stores stores suggests Y to every store that lists X
        but not Y. One suggestion per (store, Y), keeping the strongest rule."""
        sources: dict[tuple[UUID, UUID], dict[UUID, float]] = {}
        for store_id, rules in rules_by_store.items():
            strong = rules.loc[rules["lift"] >= min_lift]
            for antecedent, consequent, lift in zip(
                strong["antecedent_id"], strong["consequent_id"], strong["lift"], strict=True
            ):
                sources.setdefault((antecedent, consequent), {})[store_id] = float(lift)

        listed: set[tuple[UUID, UUID]] = {
            (store, product)
            for store, product, is_listed in zip(
                listings["store_id"], listings["product_id"], listings["is_listed"], strict=True
            )
            if bool(is_listed)
        }
        stores: list[UUID] = sorted(set(listings["store_id"]))
        best: dict[tuple[UUID, UUID], GapSuggestion] = {}
        for (antecedent, consequent), lifts in sorted(sources.items()):
            if len(lifts) < min_stores:
                continue
            lift = max(lifts.values())
            for store_id in stores:
                if (store_id, antecedent) not in listed or (store_id, consequent) in listed:
                    continue
                current = best.get((store_id, consequent))
                if current is not None and float(current.evidence["lift"]) >= lift:  # type: ignore[arg-type]
                    continue
                best[(store_id, consequent)] = GapSuggestion(
                    store_id=store_id,
                    product_id=consequent,
                    evidence={
                        "antecedent_id": str(antecedent),
                        "lift": lift,
                        "source_stores": sorted(str(s) for s in lifts),
                    },
                )
        return [best[k] for k in sorted(best)]
