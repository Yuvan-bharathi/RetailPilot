# RetailPilot AI — Decision Log

Decisions taken after the Phase 0 review (3 November 2026). Each entry records the gap found, the decision, and
the documents changed. These decisions are binding: `docs/02-technical-spec.md`, `CLAUDE.md` and
`docs/diagrams/` have been updated to match. If a later document disagrees with this log, raise it — do not
choose silently.

| ID | Date | Decided by |
|---|---|---|
| D-01 … D-12 | 2026-11-03 | Product owner (Phase 0 review) |
| D-13 … D-17 | 2026-11-03 | Product owner (review of the D-01 … D-12 interpretations) |

---

## D-01 Escalated PO lines (gap 1)
**Problem.** SD-14 escalates undecided lines to the Super Admin, but SD-10 accepted only Store Supervisors at L1,
only acted on PENDING lines and returned 409 after the deadline, so escalated lines could never be decided.
"L1 finalises when no line is PENDING" would also close a PO while escalated lines were still open.
**Decision.**
- The Super Admin may decide `ESCALATED` lines through `POST /approvals`. The approval is recorded as
  `level = "L1"` with `store_id` = the line's store (L1 on behalf of the store).
- The deadline check (409) applies only to Store Supervisors deciding `PENDING` lines.
- L1 is finalised only when **no line is `PENDING` or `ESCALATED`**.
**Changed.** Spec §2, §4; SD-10; SD-14.

## D-02 Co-replenishment trigger (gap 2)
**Problem.** SD-06 added a complement only if `available < requirement` and no need existed yet — but the main
pass already creates a need for every short product, so the rule could never trigger (or double-ordered).
**Decision.** A complement C of a reordered product P (rule lift ≥ `co_replenish.min_lift`, top
`co_replenish.limit` by lift) qualifies for co-replenishment in store S when **both** hold:
1. `available(C) − daily_demand(C) × review_period_days(C) < own_requirement(C)` — it would fall below its
   requirement before the next review; and
2. C's serving supplier for S (D-07) already delivers to **the same store S** this cycle (refined by D-13).
If C already has a need in S this run, do **not** add another: set `linked_product_id = P` and `lift` on the
existing need. Otherwise create a need with `source = "CO_REPLENISH"`,
`qty = own_requirement(C) − (available(C) − daily_demand(C) × review_period_days(C))` (ceil, ≥ 1),
`linked_product_id = P`, `lift`. Scenario 4 synthetic data is planted so this triggers.
**Changed.** Spec §1, §9; SD-06; demo scenario 4 note.

## D-03 Open transfers, open POs and run supersession (gap 3)
**Problem.** Nothing maintained `incoming` and `reserved`, so the next nightly run would re-propose the same
surplus and re-order the same need.
**Decision.**
- **Transfers.** On `DEST_ACCEPTED`: receiver `incoming += qty`, donor `reserved += qty` (soft reservation).
  On `REJECTED` / `CANCELLED` after acceptance: both released. On `DISPATCHED`: donor `reserved −= qty`
  (stock leaves via `TRANSFER_OUT`), receiver stays `incoming`. On `RECEIVED`: receiver `incoming −= qty`
  (stock arrives via `TRANSFER_IN` of `received_qty`).
- **Purchase orders.** PO lines `APPROVED` / `EDITED` on a PO that is `APPROVED` or `SUBMITTED` count as
  receiver `incoming` until goods receipt (D-08) reduces it.
- **Supersession.** At the start of each nightly run (after ingestion), the previous runs' **untouched** items
  get the new status `SUPERSEDED` and are recalculated: recommendations in `PENDING`, transfers in `PROPOSED`,
  and PO lines in `PENDING` on POs in `PENDING_L1` where no line has been decided yet (such a PO also becomes
  `SUPERSEDED`). Anything a person has acted on is kept.
- **No carry-forward.** A cancelled transfer or rejected line is simply recalculated on the next run.
  `NeedRepo.carry_forward` and `NeedRepo.reopen` are removed; source `TRANSFER_CANCELLED` is removed.
**Changed.** Spec §1, §2, §3; CLAUDE.md rule 6; SD-01 (supersede step), SD-10, SD-12, SD-14; CD-1, CD-2.

## D-04 Low-confidence SKUs (gap 4)
**Decision.** A store-SKU with forecast `confidence = "LOW"` (stale or insufficient data) gets **no automatic
PO need and no transfer** (neither as donor nor as receiver). Instead the Stock Balancing Agent writes one
`Recommendation(rec_type="REORDER", status="NEEDS_REVIEW")` with the calculated numbers as evidence when the
store-SKU is short.
**Changed.** Spec §1; SD-06, SD-07.

## D-05 REORDER recommendation for every shortfall need (gap 5)
**Decision.** Every `ReplenishmentNeed` with `source = "SHORTFALL"` gets a `Recommendation(rec_type="REORDER")`
so every PO line has a `source_rec_id`. `replenishment_need` gains `reason`
(`NO_SURPLUS_IN_ANY_STORE | PARTIAL_SURPLUS | TRANSFER_NOT_VIABLE | CO_REPLENISH`), `lift` (nullable) and
`rec_id`.
**Changed.** Spec §2, §10; SD-06; CD-1.

## D-06 Schema keys, partitioning, discrepancies (gap 6)
**Decision.**
- Composite primary keys: `store_product (store_id, product_id)`, `supplier_product (supplier_id, product_id)`,
  `supplier_store_terms (supplier_id, store_id)`, `inventory_position (store_id, product_id)`,
  `forecast (run_id, store_id, product_id)`, `kpi_snapshot (run_id, store_id, metric, product_key)`,
  `lost_sales_estimate (run_id, store_id, product_id)`, `transfer_route (from_store_id, to_store_id)`,
  `inventory_daily_snapshot (store_id, product_id, snapshot_date)`.
- `sales_line` gains `txn_date` and `line_no`; PK `(bill_id, line_no, txn_date)`; uniqueness of a bill line is
  `(bill_id, line_no)`. Partitioned by month on `txn_date`. Duplicate detection in ingestion uses
  `(bill_id, line_no)`.
- `inventory_movement` PK `(movement_id, created_at)`, partitioned by month on `created_at`.
- Transfer discrepancies live on `transfer_order`: `expected_qty`, `received_qty`, `loss_value`.
- `docs/diagrams/` (repo copy) is the source of truth; CD-1 and CD-2 updated.
**Changed.** Spec §10; SD-02, SD-12; CD-1, CD-2.

## D-07 Supplier serving a store (gap 7)
**Decision.** `store_product.preferred_supplier_id` names the supplier serving that store for that product.
Stock balancing and requirement windows use it. The PO agent may switch supplier only if the preferred one is
unavailable for the line (no offer, inactive, or cannot deliver by `required_by`); the switch is flagged in
evidence. Lead time precedence: `SupplierStoreTerms.lead_time_days` → `SupplierProduct.lead_time_days` →
`Supplier.default_lead_time_days`.
**Changed.** Spec §1, §8; SD-06, SD-09 (note); CD-1.

## D-08 Missing endpoints and goods receipt (gap 8)
**Decision.** Add: goods receipt (`POST /purchase-orders/{po_id}/receipts` → `PO_RECEIPT` movements to BACKROOM,
`incoming` reduced, PO `RECEIVED` when all lines are fully received, partial receipt allowed), `GET /transfers`,
`GET /transfers/{id}`, `GET /stores`, `GET /me`, inventory tabs (`/stores/{id}/inventory/movements`,
`/batches`, `/expiring`), in-app notifications (`GET /notifications`, `POST /notifications/{id}/read`), and
`POST /purchase-orders/{po_id}/resolve` (Super Admin resolves `NEEDS_REVIEW`: edit lines and release to
`PENDING_L1`, or reject). New sequence diagram SD-16 Goods Receipt.
**Changed.** Spec §2, §5, §8, §10; SD-16 (new).

## D-09 Daily stock history and backfill (gap 9)
**Decision.** New table `inventory_daily_snapshot (store_id, product_id, snapshot_date, shelf_qty,
backroom_qty, closing_on_hand)`, written by ingestion for each day loaded. Stockout day = `closing_on_hand = 0`.
`DataIngestionService.backfill(start, end, store_ids)` loads history day by day using the same validation as
`load_and_validate`.
**Changed.** Spec §8, §10; CD-1; SD-02 (daily snapshot write, backfill note).

## D-10 Smaller decisions
- **Aisle filter** removed from the PoC Store Inventory View; kept for the 3D extension.
- **Marginal order cost.** In `po_incremental_cost`, `order_fixed_share` and the delivery-charge share are **0**
  if a PO to the same supplier for that store is already planned in this cycle; otherwise the full
  `order_fixed_cost` and full `SupplierStoreTerms.delivery_charge`. (Replaces "`order_fixed_cost / expected_lines`".)
  How "already planned" is determined deterministically: see D-17.
- **Days to sell cap.** `days_to_sell_at_donor = qty / donor.daily_demand`, capped at `shelf_life_days`
  (or 90 if the product has no shelf life); when `daily_demand = 0` the cap is used.
- **Perishable** = `shelf_life_days ≤ perishable_max_shelf_life_days` (business setting, default 30).
- Requirements §5.6 example explanation corrected from "surplus 30" to "surplus 24".

## D-11 Environment and Phase 1 tooling
Docker Desktop and uv are being installed. Order of work: Phase 1 (scaffold) → Phase 3 (pure tools) → Phase 2
(schema, needs Docker). Python pinned to 3.12 with `.python-version`.
Phase 1 tooling approved: `pyjwt` + `bcrypt` (instead of python-jose + passlib); dev deps `pandas-stubs` and
`celery-types` for `mypy --strict`; Tailwind v4 with tokens mapped through `@theme` (design doc wording updated);
backend layout `app/domain/{models,schemas,repositories}`; synthetic data run from the repo root with
`uv run --project backend python -m data.synthetic.generate` (CLAUDE.md updated).

## D-12 Phase 0 review document trail
Gaps 1–10 are recorded above as D-01 … D-10. The business requirements document (v2.2) is otherwise unchanged.

---

## D-13 Co-replenishment needs a delivery to the same store
**Decision.** Refines D-02 condition 2. A complement qualifies only if its preferred supplier for store S is
already delivering **to store S** this cycle, i.e. a SHORTFALL need exists for `(supplier, S)`. Reason: the
delivery charge is per store, while the order fixed cost is shared per consolidated PO; adding a line to an
existing delivery to S costs nothing extra.
**Changed.** Spec §1; SD-06.

## D-14 Kept POs: pending lines count as "on order (pending)"
**Decision.** Confirms D-03: a PO is superseded only if none of its lines has been decided. For a PO that is
kept, its `PENDING` (and `ESCALATED`) lines count as **on order (pending)** in the next run: they are added to
the store's `on_order_pending` quantity, which is included in `available` for that run, so no duplicate need
or transfer is created. They do not touch `InventoryPosition.incoming` (which stays for committed stock).
**Changed.** Spec §1, §2; SD-06.

## D-15 Donor declines after acceptance
**Decision.** New transition `DEST_ACCEPTED → REJECTED` (donor declined, `POST /transfers/{id}/reject` by the
donor's supervisor, reason required). It releases the soft reservation (donor `reserved −= qty`) and the
receiver's `incoming −= qty`, and notifies the destination store. The need is recalculated by the next run.
The destination may still reject from `PROPOSED` (nothing to release).
**Changed.** Spec §2, §4, §5; SD-12; CD-2 note.

## D-16 Close PO short; overdue incoming
**Decision.**
- **Close PO short** (built in Phase 6): the Super Admin may close a `SUBMITTED` PO whose lines are partly
  received; the undelivered quantity stops counting as incoming and the PO becomes `RECEIVED` with the
  short quantities recorded. Endpoint `POST /purchase-orders/{po_id}/close-short`.
- **Overdue incoming.** Business rule `incoming_overdue_grace_days` (default 3). Incoming stock (PO lines and
  dispatched transfers) whose expected date + grace days is in the past is flagged **overdue** and is **not**
  counted in `available`. Expected date = PO submitted date + lead time (D-07 precedence); transfer dispatch
  date + `transit_days`.
**Changed.** Spec §1, §2, §5, §9; SD-06 (available uses non-overdue incoming); SD-16 note.

## D-17 Marginal order cost: two passes, by urgency
**Decision.** Replaces the order-dependent rule in D-10. For each product the Stock Balancing Agent works in two
passes:
1. **Pass 1** marks the `(supplier, store)` pairs that will need a PO regardless — short stores of products
   for which no store has surplus (`NO_SURPLUS_IN_ANY_STORE`).
2. **Pass 2** runs the transfer decision for the remaining products, processing short stores by urgency
   (`days_of_cover` ascending, then `store_id` for ties) and products by their most urgent store. For a marked
   pair the PO's marginal order cost is 0 (order fixed share and delivery share); otherwise full cost. Pairs
   that get a PO need during pass 2 are marked too.
Results are therefore deterministic for the same input.
**Changed.** Spec §1; SD-06, SD-07.
