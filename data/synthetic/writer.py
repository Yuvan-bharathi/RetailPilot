"""Write rows to CSV in the column order and formats of schema.SCHEMA (deterministic, LF line endings)."""

import csv
import json
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from data.synthetic.schema import SCHEMA, Kind


def _format(value: object, kind: Kind) -> str:
    if value is None:
        if kind in ("opt_int", "opt_date"):
            return ""
        raise ValueError(f"missing value for a {kind} column")
    if kind == "bool":
        return "true" if value else "false"
    if kind in ("date", "opt_date"):
        assert isinstance(value, date)
        return value.isoformat()
    if kind == "decimal":
        assert isinstance(value, Decimal)
        return format(value, "f")
    if kind == "uuid":
        assert isinstance(value, UUID)
        return str(value)
    return str(value)


def write_csv(directory: Path, name: str, rows: Iterable[Mapping[str, object]]) -> int:
    columns = SCHEMA[name]
    count = 0
    with (directory / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([col for col, _ in columns])
        for row in rows:
            writer.writerow([_format(row[col], kind) for col, kind in columns])
            count += 1
    return count


def write_json(directory: Path, name: str, payload: Mapping[str, object]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    (directory / name).write_text(text + "\n", encoding="utf-8", newline="\n")
