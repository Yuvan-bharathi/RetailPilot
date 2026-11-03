"""Turn one store-day of sold units into bills and bill lines.

Units are split into lines of 1–3 and spread over the day's bills. Planted complement pairs put the complement's
lines into bills that already hold the anchor product (e.g. butter into bread bills). Bulk sales get their own
bill. A few voided and return lines are added for the basket-cleaning rules; they do not move stock.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np

from data.synthetic.catalog import uid

LINE_QTY = (1, 1, 1, 2, 2, 3)
VOID_RATE = 0.01
RETURN_RATE = 0.005
PROMO_DISCOUNT = Decimal("0.05")
IST = timedelta(hours=5, minutes=30)
CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Sold:
    product_id: UUID
    units: int
    price: Decimal


@dataclass(slots=True)
class _Line:
    product_id: UUID
    qty: int
    price: Decimal
    is_return: bool = False
    is_voided: bool = False


def build_day(
    rng: np.random.Generator,
    *,
    store_code: str,
    store_id: UUID,
    day: date,
    n_bills: int,
    sold: Sequence[Sold],
    bulk: Sequence[Sold],
    pairs: Mapping[UUID, tuple[UUID, float]],
    promo: bool,
    catalog: Sequence[tuple[UUID, Decimal]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return (bill rows, line rows) for one store-day."""
    lines_by_bill: dict[int, list[_Line]] = {}
    bills_with: dict[UUID, list[int]] = {}
    anchors = {anchor for anchor, _ in pairs.values()}
    ordered = sorted(sold, key=lambda s: (0 if s.product_id in anchors else 1, s.product_id))
    for item in ordered:
        remaining = item.units
        while remaining > 0:
            qty = min(remaining, LINE_QTY[int(rng.integers(len(LINE_QTY)))])
            pair = pairs.get(item.product_id)
            anchor_bills = bills_with.get(pair[0], []) if pair else []
            if pair and anchor_bills and rng.random() < pair[1]:
                bill = anchor_bills[int(rng.integers(len(anchor_bills)))]
            else:
                bill = int(rng.integers(n_bills))
            lines_by_bill.setdefault(bill, []).append(_Line(item.product_id, qty, item.price))
            bills_with.setdefault(item.product_id, []).append(bill)
            remaining -= qty
    for k, item in enumerate(bulk):
        lines_by_bill.setdefault(n_bills + k, []).append(_Line(item.product_id, item.units, item.price))
    for flag in ("void", "return"):
        rate = VOID_RATE if flag == "void" else RETURN_RATE
        for _ in range(int(rng.binomial(n_bills, rate))):
            product_id, price = catalog[int(rng.integers(len(catalog)))]
            bill = int(rng.integers(n_bills))
            lines_by_bill.setdefault(bill, []).append(
                _Line(product_id, 1, price, is_return=flag == "return", is_voided=flag == "void")
            )

    bill_rows: list[dict[str, object]] = []
    line_rows: list[dict[str, object]] = []
    for bill in sorted(lines_by_bill):
        bill_id = uid("bill", store_code, day.isoformat(), bill)
        local = datetime(day.year, day.month, day.day, int(rng.integers(8, 22)), int(rng.integers(0, 60)))
        total = Decimal(0)
        for line_no, line in enumerate(lines_by_bill[bill], start=1):
            amount = line.price * line.qty
            discount = (
                (amount * PROMO_DISCOUNT).quantize(CENT) if promo and not line.is_return else Decimal(0)
            )
            if line.is_voided:
                discount = Decimal(0)
            elif line.is_return:
                total -= amount
            else:
                total += amount - discount
            line_rows.append(
                {
                    "bill_id": bill_id,
                    "line_no": line_no,
                    "txn_date": day,
                    "store_id": store_id,
                    "product_id": line.product_id,
                    "qty": line.qty,
                    "unit_price": line.price,
                    "discount": discount,
                    "is_return": line.is_return,
                    "is_voided": line.is_voided,
                    "is_promo_day": promo,
                }
            )
        bill_rows.append(
            {
                "bill_id": bill_id,
                "store_id": store_id,
                "txn_datetime": (local - IST).isoformat() + "Z",
                "txn_date": day,
                "total_amount": total,
            }
        )
    return bill_rows, line_rows
