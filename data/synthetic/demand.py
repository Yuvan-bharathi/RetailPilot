"""Daily demand for background products: store affinity, weekday pattern, salary week and festival spikes."""

from collections.abc import Sequence
from datetime import date

import numpy as np

from data.synthetic.catalog import CATEGORY_BY_NAME, Product, Store

WEEKDAY_FACTOR = (0.90, 0.88, 0.92, 0.96, 1.05, 1.35, 1.30)  # Monday … Sunday
SALARY_FACTOR = 1.12  # first five days of the month
FESTIVAL_FACTOR = 1.9  # festival day and the two days before, for festival-sensitive categories
FESTIVAL_LEAD_DAYS = 2


def day_factor(day: date) -> float:
    factor = WEEKDAY_FACTOR[day.weekday()]
    if day.day <= 5:
        factor *= SALARY_FACTOR
    return factor


def is_festival_window(day: date, festivals: Sequence[date]) -> bool:
    return any(0 <= (f - day).days <= FESTIVAL_LEAD_DAYS for f in festivals)


def expected_rate(product: Product, store: Store) -> float:
    category = CATEGORY_BY_NAME[product.category]
    return product.base_rate * category.affinity.get(store.store_type, 1.0)


def background_demand(
    rng: np.random.Generator,
    products: Sequence[Product],
    store: Store,
    days: Sequence[date],
    festivals: Sequence[date],
) -> np.ndarray:
    """Poisson daily units, shape (days, products)."""
    rates = np.array([expected_rate(p, store) for p in products])
    festive = np.array([CATEGORY_BY_NAME[p.category].festival for p in products])
    factors = np.array([day_factor(d) for d in days])[:, None]
    boost = np.array([is_festival_window(d, festivals) for d in days])[:, None] & festive[None, :]
    lam = rates[None, :] * factors * np.where(boost, FESTIVAL_FACTOR, 1.0)
    units: np.ndarray = np.asarray(rng.poisson(lam), dtype=np.int64)
    return units
