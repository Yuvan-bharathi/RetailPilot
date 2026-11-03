# Synthetic dataset (Phase 4a)

Pure-Python generator (numpy + pandas) that writes CSV files for three stores, with the five demo scenarios of
`docs/04-demo-scenarios.md` planted deterministically. All data is synthetic; festival dates are approximate.

```bash
# from the repo root
uv run --project backend python -m data.synthetic.generate --scenarios all --profile full --seed 42
#   --profile full | small | tiny     --scenarios all | 1,3,5     --end-date 2026-11-02     --out <dir>
```

| Profile | Products | Days | Bills / store / day (weekday-adjusted) | Use |
|---|---|---|---|---|
| full | 300 | 180 | 500 | demos, Phase 4b ingestion (~22 s, ~110 MB) |
| small | 80 | 120 | 200 | unit tests (`backend/tests/unit/synthetic`) |
| tiny | 30 | 60 | 60 | determinism / CLI tests |

The same seed and profile give byte-identical files. Ids are UUIDv5 of readable keys (stable across runs).
`end_date` is the last day of history; the nightly run is for `run_date = end_date + 1`.

## Files
Column types: uuid · str · int · decimal (₹, plain text) · date (ISO) · datetime (ISO, UTC, `Z`) · bool
(`true`/`false`) · empty = null. The authoritative column list is `schema.py`; `reader.py` parses every column.

| File | Columns | Notes |
|---|---|---|
| stores.csv | store_id, code, name, region, store_type, display_capacity | A residential · B college · C temple |
| products.csv | product_id, sku, name, category, brand, cost_price, selling_price, pack_size, shelf_life_days | shelf life empty = not perishable; perishable = ≤ 30 days |
| suppliers.csv | supplier_id, name, default_lead_time_days | 2 per category + 1 dedicated supplier per scenario |
| supplier_products.csv | supplier_id, product_id, price, lead_time_days, moq, order_pack_size | |
| supplier_store_terms.csv | supplier_id, store_id, lead_time_days, delivery_charge | lead time A 3 · B 7 · C 5 (requirements §5.3) |
| store_products.csv | store_id, product_id, preferred_supplier_id, min_display_qty, safety_stock_days, review_period_days, is_listed | review A 2 · B 2 · C 3 |
| transfer_routes.csv | from_store_id, to_store_id, fixed_cost, per_unit_cost, handling_cost_per_unit, transit_days | A→C: 150 + 2/unit + 1/unit, 1 day |
| calendar_events.csv | event_id, event_date, event_type, region, description | FESTIVAL · SALARY · PROMO |
| sales_bills.csv | bill_id, store_id, txn_datetime, txn_date, total_amount | txn_date is the IST business day |
| sales_lines.csv | bill_id, line_no, txn_date, store_id, product_id, qty, unit_price, discount, is_return, is_voided, is_promo_day | key (bill_id, line_no) |
| stock_snapshots.csv | store_id, product_id, snapshot_date, shelf_qty, backroom_qty, closing_on_hand | daily POS closing stock |
| receipts.csv | receipt_id, store_id, product_id, supplier_id, receipt_date, qty, batch_no, expiry_date | → PO_RECEIPT movements |
| write_offs.csv | store_id, product_id, write_off_date, batch_no, qty, reason | expired batches → EXPIRY_WRITE_OFF |
| batches.csv | batch_id, store_id, product_id, batch_no, qty, expiry_date | perishable batches held at the end of history |
| open_orders.csv | store_id, product_id, supplier_id, qty, order_date, expected_date | ordered, arriving after the history |
| business_rules.json | BusinessRule defaults (spec §9) | |
| manifest.json | seed, dates, store ids, planted scenarios and expected outcomes, edge cases | |

## Stock replay
For every store-product and day:

`closing_on_hand[d] = closing_on_hand[d−1] + receipts[d] − sales[d] − write_offs[d]`

where sales are lines that are neither `is_return` nor `is_voided` (returns are not restocked; voided lines never
happened). The single exception is the planted **stock mismatch** (`manifest.edge_cases.stock_mismatch`): on that
day 3 units disappear without a movement, so Phase 4b reconciliation must post an ADJUSTMENT.
Also planted: a **stale SKU** in Store C (stock held, no sales for 5 days; `manifest.edge_cases.stale_sku`).

## Planted scenarios (constant daily demand, no stockout in the last 28 days, dedicated supplier)
| # | Product | Store A | Store B | Store C | Expected |
|---|---|---|---|---|---|
| 1 | Rice 5 kg | d 10, req 65, holds 30 | d 8, req 85, holds 40 | d 9, req 86, holds 35 | PO needs 35 / 45 / 51, NO_SURPLUS_IN_ANY_STORE |
| 2 | Tea 250 g | req 16, holds 46 (surplus 30) | at requirement | req 30, holds 10 | transfer A→C 20, no PO |
| 3 | Biscuits 200 g | req 30, holds 54 (surplus 24) | at requirement (55) | req 40, holds 0 | transfer A→C 24 + PO C 16 (PARTIAL_SURPLUS) |
| 4 | Bread + butter | bread req 68, holds 30; butter req 22, holds 25 | at requirement | at requirement | bread PO 38; butter co-replenish 3 (lift ≥ 1.5) |
| 5 | Paneer 200 g | one batch of 40 expiring in 5 days, sells 2/day | at requirement | sells 8/day | 30 at risk → single transfer A→C 30 |

Scenario 3 Store C holds 0, so its last day closes at 0 (a stockout day, excluded from the baseline by D-30);
its other days have the same constant demand, so the baseline still equals the planted 4/day.
