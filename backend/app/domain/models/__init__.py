"""SQLAlchemy models (CD-1, CD-2, spec §10). Every model module is imported here so Alembic sees all tables."""

from app.domain.models.base import Base
from app.domain.models.extensions import ShelfLocation, StoreLayout, SupplierScheme
from app.domain.models.inventory import Batch, InventoryDailySnapshot, InventoryMovement, InventoryPosition
from app.domain.models.master import (
    CalendarEvent,
    Product,
    Store,
    StoreProduct,
    Supplier,
    SupplierProduct,
    SupplierStoreTerms,
)
from app.domain.models.observability import AgentRun, DecisionEvidence, LLMUsage, ToolCall
from app.domain.models.planning import (
    AssociationRule,
    Forecast,
    KpiSnapshot,
    LostSalesEstimate,
    Recommendation,
    ReplenishmentNeed,
)
from app.domain.models.purchasing import GoodsReceipt, GoodsReceiptLine, POLine, PurchaseOrder
from app.domain.models.sales import SalesLine, SalesTransaction
from app.domain.models.schema_objects import MATERIALIZED_VIEWS, PARTITIONED_TABLES
from app.domain.models.transfers import Approval, BusinessRule, TransferOrder, TransferRoute
from app.domain.models.users import AppUser, Notification

__all__ = [
    "MATERIALIZED_VIEWS",
    "PARTITIONED_TABLES",
    "AgentRun",
    "AppUser",
    "Approval",
    "AssociationRule",
    "Base",
    "Batch",
    "BusinessRule",
    "CalendarEvent",
    "DecisionEvidence",
    "Forecast",
    "GoodsReceipt",
    "GoodsReceiptLine",
    "InventoryDailySnapshot",
    "InventoryMovement",
    "InventoryPosition",
    "KpiSnapshot",
    "LLMUsage",
    "LostSalesEstimate",
    "Notification",
    "POLine",
    "Product",
    "PurchaseOrder",
    "Recommendation",
    "ReplenishmentNeed",
    "SalesLine",
    "SalesTransaction",
    "ShelfLocation",
    "Store",
    "StoreLayout",
    "StoreProduct",
    "Supplier",
    "SupplierProduct",
    "SupplierScheme",
    "SupplierStoreTerms",
    "ToolCall",
    "TransferOrder",
    "TransferRoute",
]
