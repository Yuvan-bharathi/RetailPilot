"""Business rules (spec §9): read and edit the global BusinessRule rows, with a typed, range-checked registry (D-48).

Keys inside the `basket` / `co_replenish` objects are exposed as dotted keys (`basket.min_support`), so every rule is a
scalar the UI can edit. Money and rates are stored as JSON strings (exact Decimal); counts as integers. Only the rules
listed here can be read or changed through the API — everything else stays migration-managed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorDetail, NotFound, ValidationError
from app.domain.models.transfers import BusinessRule

Kind = Literal["money", "decimal", "integer", "number", "boolean", "choice"]


@dataclass(frozen=True)
class RuleSpec:
    key: str
    group: str
    label: str
    description: str
    kind: Kind
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    choices: tuple[str, ...] | None = None


RULES: tuple[RuleSpec, ...] = (
    RuleSpec("po_l2_threshold", "Purchase orders", "L2 approval threshold", "PO value at or above which the Super Admin must also approve (L2).", "money", 0, None, "₹"),
    RuleSpec("weekly_budget", "Purchase orders", "Weekly purchase budget", "Spend cap per week; lines that do not fit go to manual review (D-29).", "money", 0, None, "₹"),
    RuleSpec("l1_deadline_hours", "Purchase orders", "L1 decision window", "Hours store supervisors have to decide their PO lines.", "integer", 1, 168, "hours"),
    RuleSpec("deadline_action", "Purchase orders", "At the L1 deadline", "What happens to undecided lines: escalate to the Super Admin or expire.", "choice", choices=("ESCALATE", "EXPIRE")),
    RuleSpec("order_fixed_cost", "Transfer vs purchase cost", "Fixed cost per purchase order", "Order handling cost used in the transfer-vs-PO comparison (rule 4).", "money", 0, None, "₹"),
    RuleSpec("holding_cost_rate_per_day", "Transfer vs purchase cost", "Holding cost rate", "Daily holding cost as a share of stock value (0.0005 ≈ 18% a year).", "decimal", 0, 0.01, "per day"),
    RuleSpec("expiry_risk_pct", "Transfer vs purchase cost", "Expiry risk of perishable surplus", "Expected expiry loss share of a donor's perishable surplus.", "decimal", 0, 1, "share"),
    RuleSpec("perishable_max_shelf_life_days", "Freshness", "Perishable up to", "Products with a shelf life up to this many days are perishable.", "integer", 1, 365, "days"),
    RuleSpec("days_to_sell_default_cap", "Freshness", "Days-to-sell cap", "Cap on days to sell donor surplus for products without a shelf life.", "integer", 1, 365, "days"),
    RuleSpec("expiry_window_days", "Freshness", "Expiry scan window", "Batches expiring within this many days are checked for risk.", "integer", 1, 60, "days"),
    RuleSpec("stale_days", "Forecasting", "Stale after", "Days without sales while stock is held before a product is low confidence.", "integer", 1, 60, "days"),
    RuleSpec("kpi_lookback_days", "Forecasting", "Demand window", "Days of in-stock history in the baseline forecast and KPIs.", "integer", 7, 180, "days"),
    RuleSpec("incoming_overdue_grace_days", "Forecasting", "Overdue grace", "Incoming stock past its expected date + grace no longer counts as available.", "integer", 0, 30, "days"),
    RuleSpec("max_steps", "Forecasting", "Agent step cap", "Maximum tool steps per agent run.", "integer", 1, 500, "steps"),
    RuleSpec("basket.min_bills", "Related products", "Minimum bills", "Stores with fewer clean bills in 90 days are skipped for basket analysis.", "integer", 1, None, "bills"),
    RuleSpec("basket.min_support", "Related products", "Minimum support", "Share of bills containing the product pair.", "number", 0, 1),
    RuleSpec("basket.min_confidence", "Related products", "Minimum confidence", "Share of bills with the first product that also contain the second.", "number", 0, 1),
    RuleSpec("basket.min_lift", "Related products", "Minimum lift", "Rules are kept when lift is above this value.", "number", 0, None),
    RuleSpec("basket.max_qty_per_line", "Related products", "Bulk line limit", "Whole bills with a line above this quantity are excluded as bulk purchases.", "integer", 1, None, "units"),
    RuleSpec("basket.exclude_promo_days", "Related products", "Exclude promotion days", "Ignore promotion days so offers do not create false associations.", "boolean"),
    RuleSpec("co_replenish.min_lift", "Related products", "Co-replenish minimum lift", "Complements are topped up only for rules at least this strong.", "number", 1, None),
    RuleSpec("co_replenish.limit", "Related products", "Complements per product", "At most this many complements are checked per reordered product.", "integer", 0, 20),
)  # fmt: skip
SPECS = {r.key: r for r in RULES}


def _bad(key: str, message: str) -> ValidationError:
    return ValidationError("Invalid business rule value", details=[ErrorDetail(field=key, message=message)])


def coerce(spec: RuleSpec, value: Any) -> Any:
    """Validate and normalise an incoming value to its stored JSON form."""
    if spec.kind == "boolean":
        if not isinstance(value, bool):
            raise _bad(spec.key, "must be true or false")
        return value
    if spec.kind == "choice":
        if value not in (spec.choices or ()):
            raise _bad(spec.key, f"must be one of {', '.join(spec.choices or ())}")
        return value
    if isinstance(value, bool):
        raise _bad(spec.key, "must be a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise _bad(spec.key, "must be a number") from exc
    if not number.is_finite():
        raise _bad(spec.key, "must be a number")
    if spec.min is not None and number < Decimal(str(spec.min)):
        raise _bad(spec.key, f"must be at least {spec.min:g}")
    if spec.max is not None and number > Decimal(str(spec.max)):
        raise _bad(spec.key, f"must be at most {spec.max:g}")
    if spec.kind == "integer":
        if number != number.to_integral_value():
            raise _bad(spec.key, "must be a whole number")
        return int(number)
    if spec.kind == "money":
        return format(number.quantize(Decimal("0.01")), "f")
    if spec.kind == "decimal":
        return format(number.normalize(), "f")
    return float(number)


def _read(rows: dict[str, Any], key: str) -> Any:
    head, _, tail = key.partition(".")
    value = rows.get(head)
    if tail:
        return value.get(tail) if isinstance(value, dict) else None
    return value


class BusinessRuleService:
    async def _global_rows(self, session: AsyncSession) -> dict[str, BusinessRule]:
        rows = await session.scalars(select(BusinessRule).where(BusinessRule.scope_store_id.is_(None)))
        return {r.rule_key: r for r in rows}

    async def list(self, session: AsyncSession) -> list[tuple[RuleSpec, Any]]:
        rows = await self._global_rows(session)
        values = {k: r.value for k, r in rows.items()}
        return [(spec, _read(values, spec.key)) for spec in RULES if _read(values, spec.key) is not None]

    async def update(self, session: AsyncSession, key: str, value: Any) -> tuple[RuleSpec, Any]:
        spec = SPECS.get(key)
        if spec is None:
            raise NotFound(f"Unknown business rule {key!r}")
        stored = coerce(spec, value)
        head, _, tail = key.partition(".")
        rows = await self._global_rows(session)
        row = rows.get(head)
        if row is None:
            raise NotFound(f"Business rule {head!r} is not configured")
        row.value = (
            ({**row.value, tail: stored} if isinstance(row.value, dict) else {tail: stored})
            if tail
            else stored
        )
        await session.commit()
        return spec, stored
