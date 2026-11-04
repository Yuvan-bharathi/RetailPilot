"""Day-by-day stock simulation for one store-product.

Order of events each day:  1. write off batches whose expiry date has come (expiry_date ≤ day)
2. receive deliveries  3. sell regular demand (earliest expiry first), then a bulk order if fully available
4. optional unrecorded shrinkage (planted stock mismatch)  5. periodic review → order (background policy)
6. close: snapshot of shelf + backroom.

By construction  closing[d] = closing[d−1] + receipts[d] − sales[d] − write_offs[d]  for every day, except a day
with planted shrinkage (the "stock mismatch" edge case).
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

FAR_FUTURE = date(9999, 12, 31)


@dataclass(slots=True)
class BatchState:
    batch_no: str
    qty: int
    expiry: date | None  # None = not perishable


@dataclass(slots=True)
class Delivery:
    """A planned delivery (scenario plan) or an order in the pipeline (background policy)."""

    day_index: int
    qty: int
    order_day_index: int = -1
    expiry_override: date | None = None


@dataclass(slots=True)
class Policy:
    """Periodic-review, order-up-to policy for background products."""

    lead_time_days: int
    review_period_days: int
    review_offset: int
    safety_stock_days: int
    min_display_qty: int
    order_pack_size: int
    initial_rate: float


@dataclass(slots=True)
class SimResult:
    sales: list[int] = field(default_factory=list)  # regular units sold per day
    bulk_sales: list[int] = field(default_factory=list)  # bulk units sold per day (one line of this qty)
    closing: list[int] = field(default_factory=list)
    shelf: list[int] = field(default_factory=list)
    receipts: list[tuple[int, int, str, date | None]] = field(default_factory=list)  # day, qty, batch, expiry
    write_offs: list[tuple[int, str, int]] = field(default_factory=list)  # day, batch_no, qty
    open_orders: list[Delivery] = field(default_factory=list)
    batches: list[BatchState] = field(default_factory=list)
    shrinkage_day: int | None = None


def _consume(batches: list[BatchState], qty: int) -> None:
    """Remove qty, earliest expiry first (non-perishable batches FIFO)."""
    batches.sort(key=lambda b: (b.expiry or FAR_FUTURE, b.batch_no))
    left = qty
    for b in batches:
        take = min(b.qty, left)
        b.qty -= take
        left -= take
        if left == 0:
            break
    batches[:] = [b for b in batches if b.qty > 0]


def simulate(
    *,
    days: list[date],
    demand: np.ndarray,
    bulk: np.ndarray,
    shelf_life: int | None,
    shelf_capacity: int,
    batch_prefix: str,
    opening_qty: int,
    opening_expiry: date | None,
    policy: Policy | None = None,
    plan: list[Delivery] | None = None,
    shrinkage: tuple[int, int] | None = None,  # (day index, units) — applied only if enough stock
) -> SimResult:
    result = SimResult()
    batches: list[BatchState] = []
    if opening_qty > 0:
        batches.append(BatchState(f"{batch_prefix}-OPEN", opening_qty, opening_expiry))
    pipeline: list[Delivery] = list(plan or [])
    received = 0
    recent_sales: list[int] = []

    for t, day in enumerate(days):
        # 1. expiry write-offs
        for b in [b for b in batches if b.expiry is not None and b.expiry <= day]:
            result.write_offs.append((t, b.batch_no, b.qty))
            batches.remove(b)
        # 2. deliveries
        for d in [d for d in pipeline if d.day_index == t]:
            pipeline.remove(d)
            if d.qty <= 0:
                continue
            received += 1
            expiry = d.expiry_override or (None if shelf_life is None else day + timedelta(days=shelf_life))
            batch_no = f"{batch_prefix}-{received:03d}"
            batches.append(BatchState(batch_no, d.qty, expiry))
            result.receipts.append((t, d.qty, batch_no, expiry))
        # 3. sales
        on_hand = sum(b.qty for b in batches)
        sold = min(int(demand[t]), on_hand)
        _consume(batches, sold)
        on_hand -= sold
        bulk_sold = int(bulk[t]) if 0 < int(bulk[t]) <= on_hand else 0
        _consume(batches, bulk_sold)
        on_hand -= bulk_sold
        result.sales.append(sold)
        result.bulk_sales.append(bulk_sold)
        recent_sales.append(sold)
        # 4. planted shrinkage (unrecorded)
        if shrinkage is not None and shrinkage[0] == t and on_hand >= shrinkage[1]:
            _consume(batches, shrinkage[1])
            on_hand -= shrinkage[1]
            result.shrinkage_day = t
        # 5. review and order (background policy)
        if policy is not None and t % policy.review_period_days == policy.review_offset:
            window = recent_sales[-14:]
            rate = sum(window) / len(window) if t >= 7 else policy.initial_rate
            target = (
                math.ceil(rate * (policy.lead_time_days + policy.review_period_days))
                + math.ceil(rate * policy.safety_stock_days)
                + policy.min_display_qty
            )
            position = on_hand + sum(d.qty for d in pipeline)
            need = target - position
            if need > 0:
                qty = math.ceil(need / policy.order_pack_size) * policy.order_pack_size
                pipeline.append(Delivery(t + policy.lead_time_days, qty, order_day_index=t))
        # 6. close
        result.closing.append(on_hand)
        result.shelf.append(min(on_hand, shelf_capacity))

    result.open_orders = sorted(pipeline, key=lambda d: d.day_index)
    result.batches = sorted(batches, key=lambda b: (b.expiry or FAR_FUTURE, b.batch_no))
    return result


def last_review_day(n_days: int, review_period: int) -> int:
    return list(range(0, n_days, review_period))[-1]


def scenario_plan(
    demand: int,
    n_days: int,
    review_period: int,
    final_on_hand: int,
    start: date | None = None,
    near_dated_age: int | None = None,
) -> tuple[int, list[Delivery]]:
    """Opening stock and deliveries so a constant-demand product never runs out and ends at `final_on_hand`.

    Deliveries on review days replace exactly the demand until the next review, keeping a buffer b; the last
    delivery is sized so the final closing stock equals `final_on_hand`. Closing stock never drops below
    min(b, final_on_hand), so the only possible stockout day is the last day when final_on_hand = 0.

    `near_dated_age` (with `start`): every delivery arrives with only that many days of shelf life left
    (near-dated supply), so batches still expire in delivery order and FEFO sells them in that order.
    """
    review_days = list(range(0, n_days, review_period))
    last = review_days[-1]
    remaining_after_last = demand * (n_days - last)
    buffer = min(2 * demand, remaining_after_last)

    def expiry(day_index: int) -> date | None:
        if near_dated_age is None or start is None:
            return None
        return start + timedelta(days=day_index + near_dated_age)

    deliveries = [
        Delivery(r, demand * (min(r + review_period, n_days) - r), expiry_override=expiry(r))
        for r in review_days[:-1]
    ]
    deliveries.append(
        Delivery(last, remaining_after_last + final_on_hand - buffer, expiry_override=expiry(last))
    )
    return buffer, deliveries
