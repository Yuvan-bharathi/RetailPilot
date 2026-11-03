"""POBuilder — supplier choice, consolidation, pack/MOQ, validation, budget, edits, split (SD-09, SD-10)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.tools.po_builder import POBuilder, POEditError
from app.tools.types import (
    BusinessRules,
    DraftPO,
    DraftPOLine,
    POLineEdit,
    ReplenishmentNeed,
    SupplierOffer,
    ValidationResult,
)
from tests.unit.tools.builders import PRODUCT, STORE_A, STORE_B, STORE_C

S1, S2, S3, S4 = (UUID(int=0x51), UUID(int=0x52), UUID(int=0x53), UUID(int=0x54))
OTHER_PRODUCT = UUID(int=0x200)
RUN_DATE = date(2026, 11, 3)


def _offer(
    supplier: UUID, price: str, lead: int, available: bool = True, product: UUID = PRODUCT
) -> SupplierOffer:
    return SupplierOffer(
        supplier_id=supplier,
        product_id=product,
        unit_price=Decimal(price),
        lead_time_days=lead,
        moq=0,
        order_pack_size=1,
        available=available,
    )


OFFERS = [_offer(S1, "50", 3), _offer(S2, "45", 6), _offer(S3, "45", 4), _offer(S4, "10", 1, available=False)]


def _need(
    store: UUID = STORE_A,
    qty: int = 10,
    preferred: UUID | None = None,
    product: UUID = PRODUCT,
    priority: str = "NORMAL",
) -> ReplenishmentNeed:
    return ReplenishmentNeed(
        store_id=store,
        product_id=product,
        qty=qty,
        run_date=RUN_DATE,
        required_by=date(2026, 11, 8),  # 5 days
        preferred_supplier_id=preferred,
        priority=priority,  # type: ignore[arg-type]
    )


def _line(
    store: UUID,
    qty: int,
    price: str,
    priority: str = "NORMAL",
    abc: str | None = None,
    status: str = "PENDING",
    pack: int = 1,
    moq: int = 0,
) -> DraftPOLine:
    return DraftPOLine(
        store_id=store,
        product_id=PRODUCT,
        qty=qty,
        unit_price=Decimal(price),
        order_pack_size=pack,
        moq=moq,
        priority=priority,  # type: ignore[arg-type]
        abc_class=abc,
        line_status=status,  # type: ignore[arg-type]
    )


RULES = BusinessRules(po_l2_threshold=Decimal("50000"), weekly_budget=Decimal("500000"))

# --- select_supplier ------------------------------------------------------------------------------------------


def test_select_supplier_cheapest_eligible_then_shorter_lead_time() -> None:
    # S2 is as cheap but too slow (6 > 5 days); S4 is unavailable; S3 beats S1 on price.
    assert POBuilder.select_supplier(_need(), OFFERS, required_by=date(2026, 11, 8)) == OFFERS[2]


def test_select_supplier_keeps_the_preferred_supplier_when_eligible() -> None:
    chosen = POBuilder.select_supplier(_need(preferred=S1), OFFERS, required_by=date(2026, 11, 8))

    assert chosen is not None and chosen.supplier_id == S1


def test_select_supplier_switches_when_preferred_cannot_deliver_in_time() -> None:
    chosen = POBuilder.select_supplier(_need(preferred=S2), OFFERS, required_by=date(2026, 11, 8))

    assert chosen is not None and chosen.supplier_id == S3


def test_select_supplier_none_when_nobody_is_eligible() -> None:
    assert POBuilder.select_supplier(_need(), OFFERS, required_by=date(2026, 11, 4)) is None


def test_select_supplier_ties_broken_by_supplier_id() -> None:
    offers = [_offer(S3, "45", 4), _offer(S2, "45", 4)]

    chosen = POBuilder.select_supplier(_need(), offers, required_by=date(2026, 11, 8), scores={S3: 1.0})

    assert chosen is not None and chosen.supplier_id == S2


# --- consolidate ------------------------------------------------------------------------------------------------


def test_consolidate_one_po_per_supplier_with_store_wise_lines() -> None:
    o1 = _offer(S1, "50", 3)
    o2 = _offer(S2, "20", 3, product=OTHER_PRODUCT)
    assigned = [
        (_need(STORE_B, 12), o1),
        (_need(STORE_A, 10), o1),
        (_need(STORE_A, 5), o1),  # same store + product → merged into one line
        (_need(STORE_C, 7, product=OTHER_PRODUCT, priority="HIGH"), o2),
    ]

    pos = POBuilder.consolidate(assigned)

    assert [po.supplier_id for po in pos] == [S1, S2]
    s1_po = pos[0]
    assert [(line.store_id, line.qty, line.unit_price) for line in s1_po.lines] == [
        (STORE_A, 15, Decimal("50")),
        (STORE_B, 12, Decimal("50")),
    ]
    assert s1_po.store_ids == (STORE_A, STORE_B)
    assert pos[1].lines[0].priority == "HIGH"
    assert all(line.line_status == "PENDING" for po in pos for line in po.lines)


# --- round_to_pack -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("qty", "pack", "moq", "expected"),
    [(16, 12, 0, 24), (16, 12, 30, 30), (24, 12, 0, 24), (0, 12, 6, 0), (5, 1, 10, 10), (1, 6, 0, 6)],
)
def test_round_to_pack(qty: int, pack: int, moq: int, expected: int) -> None:
    assert POBuilder.round_to_pack(qty, order_pack_size=pack, moq=moq) == expected


def test_round_to_pack_rejects_invalid_pack_size() -> None:
    with pytest.raises(ValueError):
        POBuilder.round_to_pack(10, order_pack_size=0, moq=0)


# --- validate ------------------------------------------------------------------------------------------------------


def test_validate_ok() -> None:
    po = DraftPO(
        supplier_id=S1,
        lines=(_line(STORE_A, 24, "10", pack=12, moq=12), _line(STORE_B, 30, "10", pack=12, moq=30)),
    )

    assert POBuilder.validate(po, RULES, budget_remaining=Decimal("1000")) == ValidationResult(ok=True)


def test_validate_reports_moq_pack_quantity_and_budget_problems() -> None:
    bad_moq = _line(STORE_A, 12, "10", pack=12, moq=24)
    bad_pack = _line(STORE_B, 13, "10", pack=12)
    bad_qty = _line(STORE_C, 0, "10")
    po = DraftPO(supplier_id=S1, lines=(bad_moq, bad_pack, bad_qty))

    result = POBuilder.validate(po, RULES, budget_remaining=Decimal("100"))

    assert result.ok is False
    assert result.errors == (
        f"MOQ_NOT_MET:{bad_moq.line_id}",
        f"PACK_SIZE:{bad_pack.line_id}",
        f"NON_POSITIVE_QTY:{bad_qty.line_id}",
        "BUDGET_EXCEEDED",
    )
    assert result.budget_exceeded is True


def test_validate_ignores_rejected_lines() -> None:
    po = DraftPO(
        supplier_id=S1, lines=(_line(STORE_A, 10, "10"), _line(STORE_B, 13, "10", pack=12, status="REJECTED"))
    )

    assert POBuilder.validate(po, RULES, budget_remaining=Decimal("100")).ok is True


# --- prioritise_within_budget ---------------------------------------------------------------------------------------


def test_budget_reduces_a_line_before_skipping_it() -> None:
    normal_a = _line(STORE_A, 40, "10", "NORMAL", "A", pack=10)  # 400
    high_c = _line(STORE_C, 30, "10", "HIGH", "C")  # 300
    high_a = _line(STORE_B, 50, "10", "HIGH", "A")  # 500
    normal_b = _line(STORE_B, 10, "10", "NORMAL", None)  # 100
    po = DraftPO(supplier_id=S1, lines=(normal_a, high_c, high_a, normal_b))

    result = POBuilder.prioritise_within_budget(po, budget=Decimal("900"))

    # HIGH/A 500 + HIGH/C 300 = 800 ; NORMAL/A reduced to 10 units (pack 10, ₹100) ; NORMAL/- no budget left
    kept = {line.line_id: line.qty for line in result.po.lines}
    assert kept == {high_a.line_id: 50, high_c.line_id: 30, normal_a.line_id: 10}
    assert result.po.total_value == Decimal("900")
    assert result.reduced == (normal_a.line_id,)
    assert result.skipped == (normal_b,)
    assert "BUDGET_TRIMMED" in result.po.flags
    assert result.po.po_id == po.po_id


def test_budget_high_priority_lines_are_attempted_first() -> None:
    normal_a = _line(STORE_A, 10, "10", "NORMAL", "A")  # 100, best ABC class
    high_c = _line(STORE_C, 10, "10", "HIGH", "C")  # 100, worst ABC class but HIGH

    result = POBuilder.prioritise_within_budget(DraftPO(S1, (normal_a, high_c)), budget=Decimal("100"))

    assert [line.line_id for line in result.po.lines] == [high_c.line_id]
    assert result.skipped == (normal_a,)


def test_budget_reduction_respects_moq() -> None:
    line = _line(STORE_A, 48, "1", pack=12, moq=24)  # can afford 20 → 12 units < MOQ 24 → skip

    result = POBuilder.prioritise_within_budget(DraftPO(S1, (line,)), budget=Decimal("20"))

    assert result.po.lines == ()
    assert result.skipped == (line,)
    assert result.reduced == ()


def test_budget_reduction_can_fall_back_to_the_moq_itself() -> None:
    line = _line(STORE_A, 60, "1", pack=12, moq=30)  # can afford 35 → 24 (< MOQ) → MOQ 30 fits

    result = POBuilder.prioritise_within_budget(DraftPO(S1, (line,)), budget=Decimal("35"))

    assert [(x.qty, x.line_id) for x in result.po.lines] == [(30, line.line_id)]
    assert result.reduced == (line.line_id,)


def test_budget_unchanged_when_everything_fits() -> None:
    po = DraftPO(supplier_id=S1, lines=(_line(STORE_A, 10, "10"),))

    result = POBuilder.prioritise_within_budget(po, budget=Decimal("100"))

    assert result.po == po
    assert result.reduced == () and result.skipped == ()


# --- apply_edits --------------------------------------------------------------------------------------------------


def _two_store_po() -> DraftPO:
    return DraftPO(supplier_id=S1, lines=(_line(STORE_A, 24, "10"), _line(STORE_B, 12, "10")))


def test_apply_edits_changes_own_store_lines_only() -> None:
    po = _two_store_po()
    line_a = po.lines[0]

    edited = POBuilder.apply_edits(po, [POLineEdit(po_line_id=line_a.line_id, qty=36)], store_id=STORE_A)

    assert (edited.lines[0].qty, edited.lines[0].line_status) == (36, "EDITED")
    assert edited.lines[1] == po.lines[1]


@pytest.mark.parametrize("case", ["other_store", "unknown_line", "non_positive", "already_decided"])
def test_apply_edits_rejects_invalid_edits(case: str) -> None:
    po = _two_store_po()
    if case == "already_decided":
        po = DraftPO(supplier_id=S1, lines=(_line(STORE_A, 24, "10", status="APPROVED"),))
    line_id = {"other_store": po.lines[-1].line_id, "unknown_line": UUID(int=0xBAD)}.get(
        case, po.lines[0].line_id
    )
    qty = 0 if case == "non_positive" else 10

    with pytest.raises(POEditError):
        POBuilder.apply_edits(po, [POLineEdit(po_line_id=line_id, qty=qty)], store_id=STORE_A)


def test_escalated_lines_can_be_edited() -> None:
    po = DraftPO(supplier_id=S1, lines=(_line(STORE_A, 24, "10", status="ESCALATED"),))

    edited = POBuilder.apply_edits(po, [POLineEdit(po.lines[0].line_id, 12)], store_id=STORE_A)

    assert edited.lines[0].qty == 12


# --- split --------------------------------------------------------------------------------------------------------


def test_split_moves_approved_lines_to_a_child_po() -> None:
    approved = _line(STORE_A, 24, "10", status="APPROVED")
    rejected = _line(STORE_B, 12, "10", status="REJECTED")
    po = DraftPO(supplier_id=S1, lines=(approved, rejected))

    child = POBuilder.split(po, [approved])

    assert child.parent_po_id == po.po_id
    assert child.po_id != po.po_id
    assert child.supplier_id == S1
    assert child.lines == (approved,)
    assert child.total_value == Decimal("240")


def test_split_rejects_foreign_or_empty_lines() -> None:
    po = _two_store_po()

    with pytest.raises(ValueError):
        POBuilder.split(po, [])
    with pytest.raises(ValueError):
        POBuilder.split(po, [_line(STORE_C, 1, "1")])


def test_total_value_counts_only_active_lines() -> None:
    po = DraftPO(
        supplier_id=S1, lines=(_line(STORE_A, 10, "10"), _line(STORE_B, 10, "10", status="REJECTED"))
    )

    assert po.total_value == Decimal("100")
    assert len(po.active_lines) == 1
