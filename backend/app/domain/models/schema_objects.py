"""Database objects the models deliberately do not describe, and the Alembic filter that skips them.

Monthly partitions (`<table>_YYYY_MM`, `<table>_default`) are created by migrations and by the Phase 5 partition
job; materialized views are created by migration 0001. Autogenerate and the drift test must not report them.
"""

import re
from typing import Any

from sqlalchemy import MetaData

PARTITIONED_TABLES = {"sales_line": "txn_date", "inventory_movement": "occurred_at"}
MATERIALIZED_VIEWS = ("mv_dashboard_store_day", "mv_inbox_counts")

PARTITION_NAME = re.compile(rf"^({'|'.join(PARTITIONED_TABLES)})_(\d{{4}}_\d{{2}}|default)$")


def make_include_object(metadata: MetaData) -> Any:
    def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        if type_ == "table" and reflected and name is not None and PARTITION_NAME.match(name):
            return False
        # indexes of skipped partitions are reported on their own; the parent's indexes are compared normally
        return not (
            type_ == "index" and reflected and compare_to is None and obj.table.name not in metadata.tables
        )

    return include_object
