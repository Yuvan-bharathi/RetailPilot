"""BasketTools — cleaning, mining (mlxtend fpgrowth), substitutes, assortment gaps (SD-05, D-22)."""

from datetime import date, timedelta
from uuid import UUID

import pandas as pd
import pytest

from app.tools.basket import BasketTools
from app.tools.types import BasketQualityRules, GapSuggestion
from tests.unit.tools.builders import STORE_A, STORE_B, STORE_C

BREAD, BUTTER, MILK, JAM, TEA = (UUID(int=0x301 + i) for i in range(5))
STORE_D = UUID(int=0xD)

# --- clean_bills ------------------------------------------------------------------------------------------------


def _lines() -> pd.DataFrame:
    rows = [
        # bill, product, qty, return, voided, promo
        (1, BREAD, 1, False, False, False),
        (1, BUTTER, 1, False, False, False),
        (1, JAM, -1, True, False, False),  # return line
        (2, MILK, 2, False, True, False),  # voided line
        (2, BREAD, 1, False, False, False),
        (3, BREAD, 30, False, False, False),  # bulk line → whole bill 3 dropped
        (3, BUTTER, 1, False, False, False),
        (4, TEA, 1, False, False, True),  # promotion day
    ]
    return pd.DataFrame(
        rows, columns=["bill_id", "product_id", "qty", "is_return", "is_voided", "is_promo_day"]
    )


def _kept(df: pd.DataFrame) -> list[tuple[int, UUID]]:
    return sorted((int(b), p) for b, p in zip(df["bill_id"], df["product_id"], strict=True))


def test_clean_bills_applies_every_rule() -> None:
    cleaned = BasketTools.clean_bills(_lines(), BasketQualityRules(max_qty_per_line=24))

    assert _kept(cleaned) == [(1, BREAD), (1, BUTTER), (2, BREAD)]


def test_clean_bills_rules_can_be_switched_off() -> None:
    rules = BasketQualityRules(
        exclude_returns=False, exclude_voided=False, max_qty_per_line=100, exclude_promo_days=False
    )

    assert len(BasketTools.clean_bills(_lines(), rules)) == 8


def test_clean_bills_bulk_limit_per_category() -> None:
    # D-27: rice is sold in larger quantities (limit 50); other categories use the default limit (24)
    lines = pd.DataFrame(
        {
            "bill_id": [1, 1, 2, 2, 3],
            "product_id": [BREAD, MILK, BUTTER, JAM, TEA],
            "qty": [30, 1, 30, 1, 30],
            "category": ["rice", "dairy", "biscuits", "jam", None],  # bill 3: unknown category → default
        }
    )
    rules = BasketQualityRules(max_qty_per_line=24, max_qty_per_line_by_category={"rice": 50})

    assert _kept(BasketTools.clean_bills(lines, rules)) == [(1, BREAD), (1, MILK)]


def test_clean_bills_tolerates_missing_optional_columns() -> None:
    lines = pd.DataFrame({"bill_id": [1, 1, 2], "product_id": [BREAD, BUTTER, MILK], "qty": [1, -1, 2]})

    cleaned = BasketTools.clean_bills(lines, BasketQualityRules())

    assert _kept(cleaned) == [(1, BREAD), (2, MILK)]  # negative qty still treated as a return


# --- to_basket_matrix / mine_rules --------------------------------------------------------------------------------


def _bills() -> pd.DataFrame:
    baskets = [[BREAD, BUTTER]] * 6 + [[BREAD]] + [[MILK]] * 3
    return pd.DataFrame([{"bill_id": i, "product_id": p} for i, basket in enumerate(baskets) for p in basket])


def test_to_basket_matrix_is_bills_by_products_of_bools() -> None:
    matrix = BasketTools.to_basket_matrix(_bills())

    assert matrix.shape == (10, 3)
    assert matrix.dtypes.unique().tolist() == [bool]
    assert matrix.loc[0, BREAD] and matrix.loc[0, BUTTER] and not matrix.loc[0, MILK]


def test_mine_rules_finds_bread_and_butter() -> None:
    rules = BasketTools.mine_rules(
        BasketTools.to_basket_matrix(_bills()), min_support=0.2, min_confidence=0.2
    )

    pairs = {(r.antecedent_id, r.consequent_id): r for r in rules.itertuples()}
    assert set(pairs) == {(BREAD, BUTTER), (BUTTER, BREAD)}
    bread_butter = pairs[(BREAD, BUTTER)]
    assert bread_butter.support == pytest.approx(0.6)
    assert bread_butter.confidence == pytest.approx(6 / 7)
    assert bread_butter.lift == pytest.approx((6 / 7) / 0.6)
    assert list(rules.columns) == ["antecedent_id", "consequent_id", "support", "confidence", "lift"]


def test_mine_rules_lift_filter_is_strict() -> None:
    basket = BasketTools.to_basket_matrix(_bills())

    assert BasketTools.mine_rules(basket, min_support=0.2, min_confidence=0.2, min_lift=2.0).empty


def test_mine_rules_with_nothing_frequent_is_empty() -> None:
    rules = BasketTools.mine_rules(BasketTools.to_basket_matrix(_bills()), min_support=0.95)

    assert rules.empty
    assert list(rules.columns) == ["antecedent_id", "consequent_id", "support", "confidence", "lift"]


# --- detect_substitutes ---------------------------------------------------------------------------------------------

DAY0 = date(2026, 10, 1)
COLA_A, COLA_B, CHIPS = (UUID(int=0x401 + i) for i in range(3))


def _daily(
    a_stockout_days: int, b_on_stockout: float = 15, b_normal: float = 10
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    stockouts: list[dict[str, object]] = []
    for i in range(14):
        day = DAY0 + timedelta(days=i)
        a_out = i >= 14 - a_stockout_days
        rows.append(
            {
                "store_id": STORE_A,
                "product_id": COLA_A,
                "day": day,
                "units": 0 if a_out else 20,
                "category": "cola",
            }
        )
        rows.append(
            {
                "store_id": STORE_A,
                "product_id": COLA_B,
                "day": day,
                "units": b_on_stockout if a_out else b_normal,
                "category": "cola",
            }
        )
        rows.append(
            {
                "store_id": STORE_A,
                "product_id": CHIPS,
                "day": day,
                "units": 20 if a_out else 10,
                "category": "snacks",
            }
        )
        if a_out:
            stockouts.append({"store_id": STORE_A, "product_id": COLA_A, "day": day})
    return pd.DataFrame(rows), pd.DataFrame(stockouts, columns=["store_id", "product_id", "day"])


def test_detect_substitutes_flags_same_category_uplift() -> None:
    daily, stockouts = _daily(a_stockout_days=3)

    subs = BasketTools.detect_substitutes(daily, stockouts)

    assert [(r.store_id, r.product_a, r.product_b) for r in subs.itertuples()] == [(STORE_A, COLA_A, COLA_B)]
    assert subs.iloc[0]["uplift"] == pytest.approx(0.5)


def test_detect_substitutes_across_categories_when_allowed() -> None:
    daily, stockouts = _daily(a_stockout_days=3)

    subs = BasketTools.detect_substitutes(daily, stockouts, same_category_only=False)

    assert {r.product_b for r in subs.itertuples()} == {COLA_B, CHIPS}


def test_detect_substitutes_needs_three_stockout_days() -> None:
    daily, stockouts = _daily(a_stockout_days=2)

    assert BasketTools.detect_substitutes(daily, stockouts).empty


def test_detect_substitutes_ignores_small_uplift_and_zero_baseline() -> None:
    small, stockouts = _daily(a_stockout_days=3, b_on_stockout=12)  # +20 % < 30 %
    zero, _ = _daily(a_stockout_days=3, b_on_stockout=5, b_normal=0)

    assert BasketTools.detect_substitutes(small, stockouts).empty
    assert BasketTools.detect_substitutes(zero, stockouts).empty


# --- find_assortment_gaps -------------------------------------------------------------------------------------------


def _rules(*rows: tuple[UUID, UUID, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"antecedent_id": a, "consequent_id": c, "support": 0.1, "confidence": 0.5, "lift": lift}
            for a, c, lift in rows
        ],
        columns=["antecedent_id", "consequent_id", "support", "confidence", "lift"],
    )


def _listings() -> pd.DataFrame:
    rows = [
        (STORE_A, BREAD, True), (STORE_A, BUTTER, True),
        (STORE_B, BREAD, True), (STORE_B, BUTTER, False),  # lists bread, butter delisted
        (STORE_C, BREAD, True), (STORE_C, BUTTER, True),
        (STORE_D, MILK, True),  # lists neither
    ]  # fmt: skip
    return pd.DataFrame(rows, columns=["store_id", "product_id", "is_listed"])


def test_find_assortment_gaps_suggests_missing_complement() -> None:
    gaps = BasketTools.find_assortment_gaps({STORE_A: _rules((BREAD, BUTTER, 2.0))}, _listings())

    assert gaps == [
        GapSuggestion(
            store_id=STORE_B,
            product_id=BUTTER,
            evidence={"antecedent_id": str(BREAD), "lift": 2.0, "source_stores": [str(STORE_A)]},
        )
    ]


def test_find_assortment_gaps_thresholds() -> None:
    weak = BasketTools.find_assortment_gaps({STORE_A: _rules((BREAD, BUTTER, 1.2))}, _listings())
    too_few_stores = BasketTools.find_assortment_gaps(
        {STORE_A: _rules((BREAD, BUTTER, 2.0))}, _listings(), min_stores=2
    )

    assert weak == []
    assert too_few_stores == []


def test_find_assortment_gaps_one_suggestion_per_store_and_product() -> None:
    # Two antecedents point at butter; store B lists both bread and jam → one butter suggestion, strongest rule.
    listings = pd.DataFrame(
        [(STORE_B, BREAD, True), (STORE_B, JAM, True), (STORE_A, BREAD, True), (STORE_A, JAM, True)],
        columns=["store_id", "product_id", "is_listed"],
    )
    rules_by_store = {STORE_A: _rules((BREAD, BUTTER, 3.0), (JAM, BUTTER, 2.0))}

    gaps = BasketTools.find_assortment_gaps(rules_by_store, listings)

    assert [(g.store_id, g.product_id, g.evidence["antecedent_id"]) for g in gaps] == [
        (STORE_A, BUTTER, str(BREAD)),
        (STORE_B, BUTTER, str(BREAD)),
    ]


def test_find_assortment_gaps_keeps_the_strongest_lift_across_stores() -> None:
    rules_by_store = {
        STORE_A: _rules((BREAD, BUTTER, 2.0)),
        STORE_C: _rules((BREAD, BUTTER, 3.0)),
    }

    gaps = BasketTools.find_assortment_gaps(rules_by_store, _listings(), min_stores=2)

    assert len(gaps) == 1
    assert gaps[0].evidence["lift"] == 3.0
    assert gaps[0].evidence["source_stores"] == sorted([str(STORE_A), str(STORE_C)])
