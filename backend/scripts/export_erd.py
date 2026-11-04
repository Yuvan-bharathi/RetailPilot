"""Export SQLAlchemy domain models to a PlantUML ERD (CD-1/CD-2 source of truth).

Usage (from backend/):
    uv run python -m scripts.export_erd [../docs/diagrams/erd.puml]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Table
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Enum, Float, Integer, Numeric, String, Uuid

from app.domain.models import Base

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "docs" / "diagrams" / "erd.puml"

# Domain grouping of tables
TABLE_GROUPS: dict[str, list[str]] = {
    "Master Data": [
        "store",
        "product",
        "store_product",
        "supplier",
        "supplier_product",
        "supplier_store_terms",
        "calendar_event",
    ],
    "Sales": [
        "sales_transaction",
        "sales_line",
    ],
    "Inventory": [
        "inventory_position",
        "inventory_movement",
        "batch",
        "inventory_daily_snapshot",
    ],
    "Planning": [
        "forecast",
        "association_rule",
        "replenishment_need",
        "recommendation",
        "lost_sales_estimate",
        "kpi_snapshot",
    ],
    "Purchasing": [
        "purchase_order",
        "po_line",
        "goods_receipt",
        "goods_receipt_line",
    ],
    "Transfers & Approvals": [
        "transfer_order",
        "transfer_route",
        "approval",
        "business_rule",
    ],
    "Users & Access": [
        "app_user",
        "notification",
    ],
    "Observability": [
        "agent_run",
        "tool_call",
        "decision_evidence",
        "llm_usage",
    ],
    "Extensions": [
        "store_layout",
        "shelf_location",
        "supplier_scheme",
    ],
}


def _type_name(col: Column[Any]) -> str:
    col_type = col.type
    if isinstance(col_type, Uuid):
        return "UUID"
    if isinstance(col_type, Integer):
        return "int"
    if isinstance(col_type, Numeric):
        return "Decimal"
    if isinstance(col_type, Float):
        return "float"
    if isinstance(col_type, Boolean):
        return "bool"
    if isinstance(col_type, Date):
        return "date"
    if isinstance(col_type, DateTime):
        return "datetime"
    if isinstance(col_type, Enum):
        return col_type.name.upper() if col_type.name else "ENUM"
    if isinstance(col_type, String):
        return f"str({col_type.length})" if col_type.length else "str"
    return str(col_type).split("(", 1)[0].upper()


def _column_marker(col: Column[Any]) -> str:
    is_pk = col.primary_key
    is_fk = bool(col.foreign_keys)
    if is_pk and is_fk:
        return " <<PK,FK>>"
    if is_pk:
        return " <<PK>>"
    if is_fk:
        return " <<FK>>"
    return ""


def _table_to_class(table_name: str) -> str:
    return "".join(word.capitalize() for word in table_name.split("_"))


def generate_puml() -> str:
    tables: dict[str, Table] = Base.metadata.tables
    all_grouped_tables = {t for group in TABLE_GROUPS.values() for t in group}
    remaining_tables = [name for name in sorted(tables.keys()) if name not in all_grouped_tables]

    groups = dict(TABLE_GROUPS)
    if remaining_tables:
        groups["Other"] = remaining_tables

    lines: list[str] = [
        "@startuml erd",
        "!include style.iuml",
        "skinparam linetype ortho",
        'title RetailPilot AI — Entity Relationship Diagram (ERD)\\n<size:11>Generated from SQLAlchemy models (app.domain.models)</size>',
        "hide empty methods",
        "",
    ]

    table_class_map: dict[str, str] = {}
    for table_name in tables:
        table_class_map[table_name] = _table_to_class(table_name)

    # Output packages
    for group_name, table_names in groups.items():
        package_id = "".join(w[0] for w in group_name.split()).upper()
        lines.append(f'package "{group_name}" as {package_id} {{')
        for tbl_name in table_names:
            if tbl_name not in tables:
                continue
            tbl = tables[tbl_name]
            cls_name = table_class_map[tbl_name]
            lines.append(f"  class {cls_name} as \"{tbl_name}\" {{")
            for col in tbl.columns:
                tname = _type_name(col)
                marker = _column_marker(col)
                lines.append(f"    +{col.name}: {tname}{marker}")
            lines.append("  }")
        lines.append("}")
        lines.append("")

    # Output relationships from foreign keys (deduplicated)
    relationships: set[str] = set()
    for child_name, child_table in sorted(tables.items()):
        child_cls = table_class_map[child_name]
        for fk in child_table.foreign_keys:
            parent_table_name = fk.column.table.name
            if parent_table_name not in table_class_map:
                continue
            parent_cls = table_class_map[parent_table_name]
            rel = f'{parent_cls} "1" -- "*" {child_cls}'
            relationships.add(rel)

    for rel in sorted(relationships):
        lines.append(rel)

    lines.append("@enduml")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    puml = generate_puml()
    target.write_text(puml, encoding="utf-8")
    print(f"ERD PlantUML written to {target.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
