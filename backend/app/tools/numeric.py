"""Numeric helpers shared by the tools (decision D-23).

- Demand × days products are rounded to 6 decimals before ceil()/floor(), so float artefacts such as
  0.1 × 30 = 3.0000000000000004 do not add a unit.
- Money is Decimal; it is rounded ROUND_HALF_UP to 0.01 only at outputs. Comparisons use unrounded values.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

DEMAND_DECIMALS = 6
_CENT = Decimal("0.01")


def ceil6(value: float) -> int:
    """ceil() after rounding to 6 decimals."""
    return math.ceil(round(value, DEMAND_DECIMALS))


def floor6(value: float) -> int:
    """floor() after rounding to 6 decimals."""
    return math.floor(round(value, DEMAND_DECIMALS))


def to_decimal(value: float) -> Decimal:
    """Exact-enough Decimal for a float quantity (6 decimals), never via binary float repr."""
    return Decimal(repr(round(value, DEMAND_DECIMALS)))


def money(value: Decimal) -> Decimal:
    """Round a money amount for output: ROUND_HALF_UP to 0.01."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)
