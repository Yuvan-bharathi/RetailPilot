"""POS data source adapters for synthetic / CSV data (SD-02)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from app.core.config import REPO_ROOT
from app.domain.schemas.ingestion import PosSource, RawBatchRow, RawBillLine, RawStockRow
from data.synthetic.reader import Dataset, load_dataset

__all__ = ["PosSource", "SyntheticPosSource"]


class SyntheticPosSource(PosSource):
    """Adapter reading from a generated synthetic Dataset in memory or on disk."""

    def __init__(self, dataset_or_path: Dataset | Path | None = None) -> None:
        if isinstance(dataset_or_path, Dataset):
            self.dataset = dataset_or_path
        elif isinstance(dataset_or_path, Path):
            self.dataset = load_dataset(dataset_or_path)
        else:
            default_path = REPO_ROOT / "data" / "synthetic" / "output"
            self.dataset = load_dataset(default_path)

    def fetch_sales(self, store_id: UUID, day: date) -> list[RawBillLine]:
        lines_df = self.dataset.sales_lines
        bills_df = self.dataset.sales_bills

        matched_lines = lines_df.loc[(lines_df["store_id"] == store_id) & (lines_df["txn_date"] == day)]
        if matched_lines.empty:
            return []

        # Merge with bills to retrieve txn_datetime
        merged = matched_lines.merge(bills_df[["bill_id", "txn_datetime"]], on="bill_id", how="left")

        rows: list[RawBillLine] = []
        tuples_iter: Iterator[Any] = iter(merged.itertuples())
        for r in tuples_iter:
            rows.append(
                RawBillLine(
                    bill_id=cast(UUID, r.bill_id),
                    line_no=int(r.line_no),
                    txn_datetime=cast(datetime, r.txn_datetime),
                    txn_date=cast(date, r.txn_date),
                    store_id=cast(UUID, r.store_id),
                    product_id=cast(UUID, r.product_id),
                    qty=int(r.qty),
                    unit_price=Decimal(str(r.unit_price)),
                    discount=Decimal(str(r.discount)),
                    is_return=bool(r.is_return),
                    is_voided=bool(r.is_voided),
                    is_promo_day=bool(r.is_promo_day),
                )
            )
        return rows

    def fetch_stock_snapshot(self, store_id: UUID, day: date) -> list[RawStockRow]:
        df = self.dataset.stock_snapshots
        matched = df.loc[(df["store_id"] == store_id) & (df["snapshot_date"] == day)]
        rows: list[RawStockRow] = []
        tuples_iter: Iterator[Any] = iter(matched.itertuples())
        for r in tuples_iter:
            rows.append(
                RawStockRow(
                    store_id=cast(UUID, r.store_id),
                    product_id=cast(UUID, r.product_id),
                    snapshot_date=cast(date, r.snapshot_date),
                    shelf_qty=int(r.shelf_qty),
                    backroom_qty=int(r.backroom_qty),
                    closing_on_hand=int(r.closing_on_hand),
                )
            )
        return rows

    def fetch_batches(self, store_id: UUID) -> list[RawBatchRow]:
        df = self.dataset.batches
        matched = df.loc[df["store_id"] == store_id]
        rows: list[RawBatchRow] = []
        tuples_iter: Iterator[Any] = iter(matched.itertuples())
        for r in tuples_iter:
            rows.append(
                RawBatchRow(
                    batch_id=cast(UUID, r.batch_id),
                    store_id=cast(UUID, r.store_id),
                    product_id=cast(UUID, r.product_id),
                    batch_no=str(r.batch_no),
                    qty=int(r.qty),
                    expiry_date=cast(date, r.expiry_date),
                )
            )
        return rows
