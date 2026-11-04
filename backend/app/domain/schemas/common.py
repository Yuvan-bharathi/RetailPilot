"""Shared DTO building blocks: money, references, paging (decision D-32).

Store scoping (CLAUDE.md rule 10): supervisor-facing DTOs show another store ONLY as `StoreRef` (id + name) plus a
quantity (`Counterpart`). Fields that would reveal another store's inventory are typed `... | None` and documented
as "Super Admin only"; services leave them null for Store Supervisors.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema


def _money_str(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


Money = Annotated[
    Decimal,
    PlainSerializer(_money_str, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "description": "Amount in ₹ (INR), 2 decimals"}
    ),
]


class DTO(BaseModel):
    """Immutable, and unknown fields are rejected so a response can never carry an unplanned field."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class StoreRef(DTO):
    store_id: UUID
    name: str


class ProductRef(DTO):
    product_id: UUID
    sku: str
    name: str
    category: str


class SupplierRef(DTO):
    supplier_id: UUID
    name: str


class Counterpart(DTO):
    """Another store as a Store Supervisor may see it: name + offered/requested quantity only."""

    store: StoreRef
    qty: int


class Page[T](DTO):
    """One page of a server-side paged list."""

    items: list[T]
    total: int = Field(ge=0, description="Total matching rows across all pages")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class PageParams(BaseModel):
    """Common query parameters of every list endpoint: ?page=&page_size=&sort=&q=

    `sort` is a field name, prefixed with "-" for descending (e.g. "-days_of_cover"); `q` is free-text search.
    Endpoint-specific filters (store_id, status, type, category …) are separate query parameters.
    """

    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=200)
    sort: str | None = Field(None, pattern=r"^-?[a-z_]{1,40}$")
    q: str | None = Field(None, max_length=100)


Role = Literal["STORE_SUPERVISOR", "SUPER_ADMIN"]
Priority = Literal["HIGH", "NORMAL"]
