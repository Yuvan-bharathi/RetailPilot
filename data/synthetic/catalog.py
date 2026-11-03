"""Master data: stores, categories, suppliers, products, offers, terms, routes and the calendar.

All names are synthetic. Festival dates are approximate 2026 dates and labelled as such.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

NAMESPACE = uuid.UUID("6f1c2a3e-8b4d-4e5f-9a0b-1c2d3e4f5a6b")


def uid(*parts: object) -> uuid.UUID:
    """Stable id from a readable key, so the same seed always gives the same ids."""
    return uuid.uuid5(NAMESPACE, "/".join(str(p) for p in parts))


# --- stores (requirements §5.3: lead time of the serving supplier + review period) --------------------------------


@dataclass(frozen=True, slots=True)
class Store:
    code: str
    name: str
    store_type: str
    lead_time_days: int
    review_period_days: int
    delivery_charge: Decimal
    display_capacity: int

    @property
    def store_id(self) -> uuid.UUID:
        return uid("store", self.code)


STORES: tuple[Store, ...] = (
    Store("A", "Store A - Residential", "residential", 3, 2, Decimal("150"), 1200),
    Store("B", "Store B - College area", "college", 7, 2, Decimal("250"), 900),
    Store("C", "Store C - Temple street", "temple", 5, 3, Decimal("200"), 1000),
)
REGION = "Chennai (synthetic)"

# --- categories ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Category:
    name: str
    label: str
    weight: float
    shelf_life: tuple[int, int] | None  # days; None = not perishable
    price: tuple[int, int]  # selling price range, ₹
    pack_sizes: tuple[int, ...]  # supplier order pack sizes
    festival: bool  # sells more around festivals
    base_rate: float  # typical units / store / day
    affinity: dict[str, float] = field(default_factory=dict)  # store_type → demand multiplier


CATEGORIES: tuple[Category, ...] = (
    Category(
        "staples", "Staples", 0.20, None, (60, 450), (1, 5, 10), True, 4.0, {"college": 0.7, "temple": 1.2}
    ),
    Category("dairy", "Dairy", 0.10, (6, 21), (25, 120), (6, 12), False, 5.0, {"temple": 1.2}),
    Category("bakery", "Bakery", 0.06, (3, 6), (30, 80), (6, 12), False, 4.0, {"college": 1.3}),
    Category("biscuits", "Biscuits & snacks", 0.18, None, (10, 60), (12, 24), True, 5.0, {"college": 1.5}),
    Category("beverages", "Beverages", 0.14, None, (20, 250), (6, 12, 24), True, 3.0, {"college": 1.4}),
    Category("personal_care", "Personal care", 0.16, None, (40, 350), (6, 12), False, 1.5, {"college": 0.8}),
    Category("household", "Household", 0.16, None, (30, 300), (6, 12), False, 1.5, {"college": 0.8}),
)
CATEGORY_BY_NAME = {c.name: c for c in CATEGORIES}
BRANDS = ("Brand A", "Brand B", "Brand C", "Brand D", "Brand E", "Brand F")

# --- products, suppliers -------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Product:
    sku: str
    name: str
    category: str
    brand: str
    cost_price: Decimal
    selling_price: Decimal
    order_pack_size: int
    shelf_life_days: int | None
    base_rate: float  # units / day before store affinity and seasonality
    scenario: int | None = None

    @property
    def product_id(self) -> uuid.UUID:
        return uid("product", self.sku)


@dataclass(frozen=True, slots=True)
class Supplier:
    key: str
    name: str
    default_lead_time_days: int = 5

    @property
    def supplier_id(self) -> uuid.UUID:
        return uid("supplier", self.key)


@dataclass(frozen=True, slots=True)
class Offer:
    supplier: Supplier
    product: Product
    price: Decimal
    lead_time_days: int
    moq: int


@dataclass(frozen=True, slots=True)
class Route:
    from_store: Store
    to_store: Store
    fixed_cost: Decimal
    per_unit_cost: Decimal
    handling_cost_per_unit: Decimal
    transit_days: int


@dataclass(frozen=True, slots=True)
class Event:
    event_date: date
    event_type: str
    description: str


def background_suppliers() -> dict[str, tuple[Supplier, Supplier]]:
    """Two distributors per category (primary, secondary)."""
    return {
        c.name: (
            Supplier(f"{c.name}-1", f"{c.label} distributor 1 (synthetic)"),
            Supplier(f"{c.name}-2", f"{c.label} distributor 2 (synthetic)"),
        )
        for c in CATEGORIES
    }


def make_background_products(rng: np.random.Generator, count: int) -> list[Product]:
    weights = np.array([c.weight for c in CATEGORIES])
    picks = rng.choice(len(CATEGORIES), size=count, p=weights / weights.sum())
    products: list[Product] = []
    for i, ci in enumerate(picks):
        category = CATEGORIES[int(ci)]
        selling = Decimal(int(rng.integers(category.price[0], category.price[1] + 1)))
        cost = (selling * Decimal(str(round(float(rng.uniform(0.72, 0.88)), 2)))).quantize(Decimal("0.01"))
        shelf = (
            None
            if category.shelf_life is None
            else int(rng.integers(category.shelf_life[0], category.shelf_life[1] + 1))
        )
        rate = category.base_rate * float(rng.lognormal(0.0, 0.7))
        if rng.random() < 0.15:  # slow, intermittent sellers
            rate *= 0.12
        products.append(
            Product(
                sku=f"SKU{i + 1:04d}",
                name=f"{category.label} item {i + 1:03d}",
                category=category.name,
                brand=BRANDS[int(rng.integers(len(BRANDS)))],
                cost_price=cost,
                selling_price=selling,
                order_pack_size=int(rng.choice(category.pack_sizes)),
                shelf_life_days=shelf,
                base_rate=round(rate, 4),
            )
        )
    return products


def make_routes(rng: np.random.Generator) -> list[Route]:
    routes: list[Route] = []
    for a in STORES:
        for b in STORES:
            if a == b:
                continue
            if (a.code, b.code) == ("A", "C"):  # the route the demo scenarios rely on
                routes.append(Route(a, b, Decimal("150"), Decimal("2"), Decimal("1"), 1))
                continue
            routes.append(
                Route(
                    a,
                    b,
                    Decimal(int(rng.integers(150, 301))),
                    Decimal(int(rng.integers(1, 4))),
                    Decimal("1"),
                    int(rng.integers(1, 3)),
                )
            )
    return routes


# Approximate 2026 festival dates for a synthetic Tamil Nadu / pan-India calendar (not authoritative).
FESTIVALS_2026: tuple[tuple[date, str], ...] = (
    (date(2026, 8, 28), "Raksha Bandhan"),
    (date(2026, 9, 14), "Ganesh Chaturthi"),
    (date(2026, 10, 11), "Navratri begins"),
    (date(2026, 10, 20), "Dussehra"),
    (date(2026, 11, 8), "Diwali"),
)


def make_calendar(start: date, end: date) -> list[Event]:
    horizon = end + timedelta(days=30)
    events = [
        Event(d, "FESTIVAL", f"{name} (approximate date, synthetic)")
        for d, name in FESTIVALS_2026
        if start <= d <= horizon
    ]
    day = date(start.year, start.month, 1)
    while day <= horizon:
        if day >= start:
            events.append(Event(day, "SALARY", "Salary day (approximate, synthetic)"))
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    for promo in (start + timedelta(days=20), end - timedelta(days=40)):
        if start <= promo <= end:
            events.append(Event(promo, "PROMO", "Weekend promotion (approximate, synthetic)"))
    return sorted(events, key=lambda e: (e.event_date, e.event_type))
