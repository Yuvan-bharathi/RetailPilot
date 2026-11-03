"""POBuilder — supplier choice, consolidation, pack/MOQ rounding, validation, budget, edits, split (SD-09, SD-10)."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.tools.types import (
    BusinessRules,
    DraftPO,
    DraftPOLine,
    POLineEdit,
    ReplenishmentNeed,
    SupplierOffer,
    ValidationResult,
)

EDITABLE_STATUSES = frozenset({"PENDING", "ESCALATED"})
_ABC_RANK = {"A": 0, "B": 1, "C": 2}


class POEditError(ValueError):
    """An edit is not allowed (wrong store, unknown or decided line, non-positive quantity)."""


class POBuilder:
    @staticmethod
    def select_supplier(
        need: ReplenishmentNeed,
        offers: Sequence[SupplierOffer],
        required_by: date,
        scores: Mapping[UUID, float] | None = None,
    ) -> SupplierOffer | None:
        """Eligible = available and delivers by `required_by`. Preferred supplier wins if eligible (D-07);
        otherwise lowest price → shorter lead time → supplier id. `scores` is reserved for Phase 2."""
        del scores  # supplier scorecard is a Phase 2 extension
        days_available = (required_by - need.run_date).days
        eligible = [o for o in offers if o.available and o.lead_time_days <= days_available]
        for offer in eligible:
            if offer.supplier_id == need.preferred_supplier_id:
                return offer
        if not eligible:
            return None
        return min(eligible, key=lambda o: (o.unit_price, o.lead_time_days, o.supplier_id))

    @staticmethod
    def consolidate(assigned: Sequence[tuple[ReplenishmentNeed, SupplierOffer]]) -> list[DraftPO]:
        """One DraftPO per supplier with one line per (store, product); quantities of duplicates are summed."""
        by_supplier: dict[UUID, dict[tuple[UUID, UUID], DraftPOLine]] = {}
        for need, offer in assigned:
            lines = by_supplier.setdefault(offer.supplier_id, {})
            key = (need.store_id, need.product_id)
            existing = lines.get(key)
            if existing is not None:
                lines[key] = replace(existing, qty=existing.qty + need.qty)
                continue
            lines[key] = DraftPOLine(
                store_id=need.store_id,
                product_id=need.product_id,
                qty=need.qty,
                unit_price=offer.unit_price,
                order_pack_size=offer.order_pack_size,
                moq=offer.moq,
                priority=need.priority,
                abc_class=need.abc_class,
                source_rec_id=need.source_rec_id,
            )
        return [
            DraftPO(supplier_id=supplier_id, lines=tuple(lines[k] for k in sorted(lines)))
            for supplier_id, lines in sorted(by_supplier.items())
        ]

    @staticmethod
    def round_to_pack(qty: int, order_pack_size: int, moq: int) -> int:
        """max(moq, ceil(qty / pack) × pack); 0 stays 0."""
        if order_pack_size <= 0:
            raise ValueError("order_pack_size must be positive")
        if qty <= 0:
            return 0
        return max(moq, math.ceil(qty / order_pack_size) * order_pack_size)

    @staticmethod
    def validate(po: DraftPO, rules: BusinessRules, budget_remaining: Decimal) -> ValidationResult:
        """Line checks (positive qty, MOQ, pack multiple — a qty equal to the MOQ is accepted) and budget."""
        del rules  # thresholds used here come from the lines; kept for the spec signature and later rules
        errors: list[str] = []
        for line in po.active_lines:
            if line.qty <= 0:
                errors.append(f"NON_POSITIVE_QTY:{line.line_id}")
            elif line.qty < line.moq:
                errors.append(f"MOQ_NOT_MET:{line.line_id}")
            elif line.qty % line.order_pack_size != 0 and line.qty != line.moq:
                errors.append(f"PACK_SIZE:{line.line_id}")
        if po.total_value > budget_remaining:
            errors.append("BUDGET_EXCEEDED")
        return ValidationResult(ok=not errors, errors=tuple(errors))

    @staticmethod
    def prioritise_within_budget(po: DraftPO, budget: Decimal) -> DraftPO:
        """Keep lines HIGH before NORMAL, then ABC A→C→unclassified, while they fit the budget (D-22)."""
        ordered = sorted(
            po.active_lines,
            key=lambda line: (
                0 if line.priority == "HIGH" else 1,
                _ABC_RANK.get(line.abc_class or "", 3),
                line.store_id,
                line.product_id,
            ),
        )
        kept: set[UUID] = set()
        spent = Decimal(0)
        for line in ordered:
            if spent + line.value <= budget:
                kept.add(line.line_id)
                spent += line.value
        if len(kept) == len(po.active_lines):
            return po
        lines = tuple(line for line in po.lines if line.line_id in kept)
        return replace(po, lines=lines, flags=(*po.flags, "BUDGET_TRIMMED"))

    @staticmethod
    def apply_edits(po: DraftPO, edits: Sequence[POLineEdit], store_id: UUID) -> DraftPO:
        """Change quantities of the given store's undecided lines; edited lines become EDITED (SD-10)."""
        by_id = {line.line_id: line for line in po.lines}
        changes: dict[UUID, int] = {}
        for edit in edits:
            line = by_id.get(edit.po_line_id)
            if line is None:
                raise POEditError(f"line {edit.po_line_id} is not on PO {po.po_id}")
            if line.store_id != store_id:
                raise POEditError(f"line {edit.po_line_id} belongs to another store")
            if line.line_status not in EDITABLE_STATUSES:
                raise POEditError(f"line {edit.po_line_id} is already {line.line_status}")
            if edit.qty <= 0:
                raise POEditError("edited quantity must be positive; reject the line instead")
            changes[line.line_id] = edit.qty
        lines = tuple(
            replace(line, qty=changes[line.line_id], line_status="EDITED")
            if line.line_id in changes
            else line
            for line in po.lines
        )
        return replace(po, lines=lines)

    @staticmethod
    def split(po: DraftPO, lines: Sequence[DraftPOLine]) -> DraftPO:
        """Child PO holding `lines` (approved/edited lines of `po`), linked by parent_po_id (SD-10, SD-14)."""
        if not lines:
            raise ValueError("split needs at least one line")
        own = {line.line_id for line in po.lines}
        if any(line.line_id not in own for line in lines):
            raise ValueError("split lines must belong to the parent PO")
        return DraftPO(supplier_id=po.supplier_id, lines=tuple(lines), parent_po_id=po.po_id, po_id=uuid4())
