"""Load a generated dataset into typed pandas DataFrames (UUID, date, Decimal, bool values).

This is also the reference for the Phase 4b PosSource adapter: it shows how every column is parsed.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

from data.synthetic.schema import SCHEMA, Kind


def _parse(series: pd.Series, kind: Kind) -> pd.Series:
    values = series.tolist()
    if kind == "uuid":
        return pd.Series([UUID(v) for v in values], index=series.index, dtype=object)
    if kind == "int":
        return series.astype("int64")
    if kind == "decimal":
        return pd.Series([Decimal(v) for v in values], index=series.index, dtype=object)
    if kind == "date":
        return pd.Series([date.fromisoformat(v) for v in values], index=series.index, dtype=object)
    if kind == "opt_date":
        return pd.Series(
            [date.fromisoformat(v) if v else None for v in values], index=series.index, dtype=object
        )
    if kind == "opt_int":
        return pd.Series([int(v) if v else None for v in values], index=series.index, dtype=object)
    if kind == "datetime":
        return pd.Series(
            [datetime.fromisoformat(v.replace("Z", "+00:00")) for v in values],
            index=series.index,
            dtype=object,
        )
    if kind == "bool":
        return series == "true"
    return series


def read_csv(directory: Path, name: str) -> pd.DataFrame:
    raw = pd.read_csv(directory / name, dtype=str, keep_default_na=False)
    for column, kind in SCHEMA[name]:
        raw[column] = _parse(raw[column], kind)
    return raw


@dataclass(frozen=True, slots=True)
class Dataset:
    stores: pd.DataFrame
    products: pd.DataFrame
    suppliers: pd.DataFrame
    supplier_products: pd.DataFrame
    supplier_store_terms: pd.DataFrame
    store_products: pd.DataFrame
    transfer_routes: pd.DataFrame
    calendar_events: pd.DataFrame
    sales_bills: pd.DataFrame
    sales_lines: pd.DataFrame
    stock_snapshots: pd.DataFrame
    receipts: pd.DataFrame
    write_offs: pd.DataFrame
    batches: pd.DataFrame
    open_orders: pd.DataFrame
    business_rules: dict[str, Any]
    manifest: dict[str, Any]


def load_dataset(directory: Path) -> Dataset:
    frames = {name.removesuffix(".csv"): read_csv(directory, name) for name in SCHEMA}
    business_rules = json.loads((directory / "business_rules.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    return Dataset(**frames, business_rules=business_rules, manifest=manifest)
