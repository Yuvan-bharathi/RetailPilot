"""Synthetic dataset integrity: stock replay, planted edge cases, realism, basket data, determinism, CLI."""

import hashlib
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest

from data.synthetic.config import GeneratorConfig, Profile
from data.synthetic.generate import CSV_FILES, generate, main
from data.synthetic.reader import Dataset, load_dataset

TINY = Profile(name="tiny", n_products=30, days=60, bills_per_store_day=60)


def _sales_by_day(ds: Dataset) -> pd.Series:
    lines = ds.sales_lines
    valid = lines.loc[~lines["is_voided"] & ~lines["is_return"] & (lines["qty"] > 0)]
    return valid.groupby(["store_id", "product_id", "txn_date"])["qty"].sum()


# --- files and keys ----------------------------------------------------------------------------------------------


def test_every_file_is_written(dataset_dir: Path) -> None:
    for name in (*CSV_FILES, "business_rules.json", "manifest.json"):
        assert (dataset_dir / name).is_file(), name


def test_keys_are_unique(dataset: Dataset) -> None:
    assert not dataset.sales_lines.duplicated(["bill_id", "line_no"]).any()
    assert dataset.sales_bills["bill_id"].is_unique
    assert not dataset.stock_snapshots.duplicated(["store_id", "product_id", "snapshot_date"]).any()
    assert dataset.products["sku"].is_unique
    assert all(isinstance(v, UUID) for v in dataset.products["product_id"])


def test_every_listed_store_product_has_a_preferred_supplier_with_terms(dataset: Dataset) -> None:
    offers = set(
        zip(dataset.supplier_products["supplier_id"], dataset.supplier_products["product_id"], strict=True)
    )
    terms = set(
        zip(
            dataset.supplier_store_terms["supplier_id"], dataset.supplier_store_terms["store_id"], strict=True
        )
    )
    for row in dataset.store_products.itertuples():
        assert (row.preferred_supplier_id, row.product_id) in offers
        assert (row.preferred_supplier_id, row.store_id) in terms


def test_store_windows_match_the_requirements_table(dataset: Dataset) -> None:
    # requirements §5.3: A 3+2, B 7+2, C 5+3
    stores = {UUID(v): k for k, v in dataset.manifest["stores"].items()}
    leads = {stores[r.store_id]: int(r.lead_time_days) for r in dataset.supplier_store_terms.itertuples()}
    reviews = {stores[r.store_id]: int(r.review_period_days) for r in dataset.store_products.itertuples()}
    assert leads == {"A": 3, "B": 7, "C": 5}
    assert reviews == {"A": 2, "B": 2, "C": 3}


# --- stock -----------------------------------------------------------------------------------------------------------


def test_stock_is_never_negative_and_shelf_plus_backroom_is_on_hand(dataset: Dataset) -> None:
    snaps = dataset.stock_snapshots
    assert (snaps[["shelf_qty", "backroom_qty", "closing_on_hand"]] >= 0).all().all()
    assert (snaps["shelf_qty"] + snaps["backroom_qty"] == snaps["closing_on_hand"]).all()


def test_replaying_receipts_sales_and_write_offs_reproduces_every_snapshot_except_the_planted_mismatch(
    dataset: Dataset,
) -> None:
    sales = _sales_by_day(dataset)
    receipts = dataset.receipts.groupby(["store_id", "product_id", "receipt_date"])["qty"].sum()
    write_offs = dataset.write_offs.groupby(["store_id", "product_id", "write_off_date"])["qty"].sum()

    mismatches: list[tuple[UUID, UUID, date, int]] = []
    snaps = dataset.stock_snapshots.sort_values(["store_id", "product_id", "snapshot_date"])
    for (store, product), group in snaps.groupby(["store_id", "product_id"]):
        previous: int | None = None
        for day, closing in zip(group["snapshot_date"], group["closing_on_hand"], strict=True):
            if previous is not None:
                key = (store, product, day)
                replay = (
                    previous
                    + int(receipts.get(key, 0))
                    - int(sales.get(key, 0))
                    - int(write_offs.get(key, 0))
                )
                if replay != closing:
                    mismatches.append((store, product, day, int(closing) - replay))
            previous = int(closing)

    planted = dataset.manifest["edge_cases"]["stock_mismatch"]
    assert mismatches == [
        (
            UUID(planted["store_id"]),
            UUID(planted["product_id"]),
            date.fromisoformat(planted["date"]),
            planted["delta"],
        )
    ]


def test_perishable_batches_add_up_to_on_hand_and_are_not_expired(dataset: Dataset) -> None:
    end = date.fromisoformat(dataset.manifest["end_date"])
    perishable = set(dataset.products.loc[dataset.products["shelf_life_days"].notna(), "product_id"])
    last = dataset.stock_snapshots.loc[dataset.stock_snapshots["snapshot_date"] == end]
    on_hand = {(r.store_id, r.product_id): int(r.closing_on_hand) for r in last.itertuples()}
    batch_qty = dataset.batches.groupby(["store_id", "product_id"])["qty"].sum()

    for (store, product), qty in on_hand.items():
        if product in perishable:
            assert int(batch_qty.get((store, product), 0)) == qty
    assert (dataset.batches["expiry_date"] > end).all()
    assert (dataset.batches["qty"] > 0).all()


def test_open_orders_arrive_after_the_history(dataset: Dataset) -> None:
    end = date.fromisoformat(dataset.manifest["end_date"])
    assert (dataset.open_orders["expected_date"] > end).all()


def test_planted_stale_sku(dataset: Dataset) -> None:
    stale = dataset.manifest["edge_cases"]["stale_sku"]
    store, product = UUID(stale["store_id"]), UUID(stale["product_id"])
    run_date = date.fromisoformat(dataset.manifest["run_date"])
    sale_days = [d for (s, p, d) in _sales_by_day(dataset).index if s == store and p == product]
    last = dataset.stock_snapshots.loc[
        (dataset.stock_snapshots["store_id"] == store)
        & (dataset.stock_snapshots["product_id"] == product)
        & (dataset.stock_snapshots["snapshot_date"] == run_date - timedelta(days=1))
    ]

    assert max(sale_days) == date.fromisoformat(stale["last_sale_date"])
    assert (run_date - max(sale_days)).days > int(dataset.business_rules["stale_days"])
    assert int(last["closing_on_hand"].iloc[0]) > 0


# --- realism -----------------------------------------------------------------------------------------------------------


def test_background_products_have_some_stockouts(dataset: Dataset) -> None:
    scenario_products = {UUID(p) for p in dataset.manifest["scenario_product_ids"]}
    snaps = dataset.stock_snapshots
    background = snaps.loc[~snaps["product_id"].isin(scenario_products)]
    share = float((background["closing_on_hand"] == 0).mean())
    assert 0.001 < share < 0.15


def test_weekends_sell_more_than_weekdays(dataset: Dataset) -> None:
    per_day = _sales_by_day(dataset).groupby(level="txn_date").sum()
    weekend = per_day[[d.weekday() >= 5 for d in per_day.index]]
    weekday = per_day[[d.weekday() < 5 for d in per_day.index]]
    assert weekend.mean() > 1.1 * weekday.mean()


def test_festival_spike(dataset: Dataset) -> None:
    per_day = _sales_by_day(dataset).groupby(level="txn_date").sum()
    events = dataset.calendar_events
    festivals = events.loc[(events["event_type"] == "FESTIVAL") & events["event_date"].isin(per_day.index)]
    assert not festivals.empty
    assert all("approximate" in d.lower() and "synthetic" in d.lower() for d in events["description"])
    for day in festivals["event_date"]:
        window = per_day[
            [day - timedelta(days=k) for k in range(3) if day - timedelta(days=k) in per_day.index]
        ]
        assert window.mean() > 1.2 * per_day.median()


def test_basket_cleaning_cases_exist(dataset: Dataset) -> None:
    lines = dataset.sales_lines
    assert lines["is_return"].any()
    assert lines["is_voided"].any()
    assert lines["is_promo_day"].any()
    assert (lines["qty"] > int(dataset.business_rules["basket"]["max_qty_per_line"])).any()  # bulk lines


def test_enough_bills_per_store_for_basket_mining(dataset: Dataset) -> None:
    end = date.fromisoformat(dataset.manifest["end_date"])
    recent = dataset.sales_bills.loc[dataset.sales_bills["txn_date"] > end - timedelta(days=90)]
    per_store = recent.groupby("store_id")["bill_id"].nunique()
    assert len(per_store) == 3
    assert (per_store >= int(dataset.business_rules["basket"]["min_bills"])).all()


def test_bill_totals_match_their_lines(dataset: Dataset) -> None:
    lines = dataset.sales_lines.loc[~dataset.sales_lines["is_voided"]].copy()
    sign = lines["is_return"].map({True: -1, False: 1})
    lines["amount"] = [
        q * p * s - d
        for q, p, s, d in zip(lines["qty"], lines["unit_price"], sign, lines["discount"], strict=True)
    ]
    totals = lines.groupby("bill_id")["amount"].sum()
    bills = dataset.sales_bills.set_index("bill_id")["total_amount"]
    assert (totals.reindex(bills.index, fill_value=0) == bills).all()


# --- determinism and CLI ---------------------------------------------------------------------------------------------


def _hashes(directory: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir())}


def test_same_seed_gives_identical_files(tmp_path: Path) -> None:
    generate(GeneratorConfig(profile=TINY), tmp_path / "one")
    generate(GeneratorConfig(profile=TINY), tmp_path / "two")

    assert _hashes(tmp_path / "one") == _hashes(tmp_path / "two")


def test_different_seed_gives_different_sales(tmp_path: Path) -> None:
    generate(GeneratorConfig(profile=TINY, seed=1), tmp_path / "one")
    generate(GeneratorConfig(profile=TINY, seed=2), tmp_path / "two")

    assert _hashes(tmp_path / "one")["sales_lines.csv"] != _hashes(tmp_path / "two")["sales_lines.csv"]


def test_cli_generates_a_subset_of_scenarios(tmp_path: Path) -> None:
    assert main(["--profile", "tiny", "--seed", "7", "--scenarios", "3", "--out", str(tmp_path)]) == 0

    ds = load_dataset(tmp_path)
    assert sorted(ds.manifest["scenarios"]) == ["3"]
    assert ds.manifest["seed"] == 7


@pytest.mark.parametrize("bad", [["--scenarios", "6"], ["--profile", "huge"]])
def test_cli_rejects_bad_arguments(tmp_path: Path, bad: list[str]) -> None:
    with pytest.raises(SystemExit):
        main([*bad, "--out", str(tmp_path)])
