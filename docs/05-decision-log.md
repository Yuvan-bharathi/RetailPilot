# RetailPilot AI — Decision Log

Decisions taken after the Phase 0 review (3 November 2026). Each entry records the gap found, the decision, and
the documents changed. These decisions are binding: `docs/02-technical-spec.md`, `CLAUDE.md` and
`docs/diagrams/` have been updated to match. If a later document disagrees with this log, raise it — do not
choose silently.

| ID | Date | Decided by |
|---|---|---|
| D-01 … D-12 | 2026-11-03 | Product owner (Phase 0 review) |
| D-13 … D-17 | 2026-11-03 | Product owner (review of the D-01 … D-12 interpretations) |
| D-18 … D-26 | 2026-11-03 | Product owner (Phase 1 acceptance, Phase 3 approval) |
| D-27 … D-29 | 2026-11-03 | Product owner (Phase 3 acceptance) |
| D-30 | 2026-11-03 | Product owner (Phase 4a approval) |
| D-31 | 2026-11-04 | Product owner (approved after Phase 4a finding) |
| D-32 | 2026-11-04 | Product owner (Phase 7 approval; choices confirmed with per-viewer scoping) |
| D-33 | 2026-11-04 | Product owner (contrast, Design System v1.1) |
| D-34 | 2026-11-04 | Product owner (Phase 8a contract, mock data) + implementation choices to confirm |

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

---

## D-18 Additional error codes
**Decision.** The standard error body (spec §5) also uses `UNAUTHORIZED` (401, missing/invalid credentials) and
`INTERNAL` (500, unhandled error; no internal details are returned).
**Changed.** Spec §5.

## D-19 Tool inputs: protocols and DraftPO
**Decision.** `app/tools` never imports ORM models. Parameters that the spec types as ORM models
(`TransferRoute`, `SupplierStoreTerms`, `PurchaseOrder`, `POLine`, `Batch`) are typed as read-only
`Protocol`s in `app/tools/types.py`, so ORM objects (Phase 2) and plain dataclasses both satisfy them.
`POBuilder.apply_edits` and `POBuilder.split` operate on the tool dataclass `DraftPO`; services convert
ORM ↔ `DraftPO`. Tool-side value types (`StoreState`, `CostInputs`, `TransferPlan`, …) are frozen dataclasses;
`StoreState.surplus` and `.days_of_cover` are derived properties so they can never disagree with
`available` / `requirement`.
**Changed.** Spec §8 note.

## D-20 FEFO helper
**Decision.** New pure function `FreshnessTools.at_risk_by_batch(batches, daily_demand, run_date)` implementing the
spec §1 FEFO formula; used by the Freshness Agent (SD-08).
**Changed.** Spec §8.

## D-21 Lost sales: censored demand
**Decision.** A **stockout day** is a day with `closing_on_hand = 0` — this includes days that opened with stock
> 0 and sold out (censored demand). Stockout days are **excluded** from the demand-rate average; in-stock days
with zero sales are **included**. `lost_units = demand_rate × stockout_days`. Confidence is `LOW` when there are
fewer than 7 in-stock days. `estimate()` expects `daily_sales` zero-filled for the window and `margins` with
`selling_price` and `unit_margin` per product.
**Changed.** Spec §1, §8.

## D-22 Analytics defaults
**Decision (approved).**
- ABC is computed **per store**. XYZ uses the coefficient of variation of daily units over all days in the
  window (population std; mean 0 → Z).
- Substitutes: B's "normal level" is B's mean daily units on days A was in stock; A must have **≥ 3 stockout days**
  (`min_stockout_days = 3`) before B can be flagged.
- Assortment gap: a rule X→Y with lift ≥ `min_lift` that holds in ≥ `min_stores` stores suggests Y to every
  store that lists X but not Y.

**Implementation choices (Phase 3, to confirm).**
- ABC: an item is A while the cumulative value share **before** it is < `a_cut` (so the top item is always A),
  B while < `b_cut`, else C. Ties ordered by id.
- ADI = days in window / days with non-zero sales (∞ when no sales).
- `baseline_avg_daily`: mean of daily units over the last `window_days` days present in the zero-filled series.
- `mine_rules` keeps rules with lift **>** `min_lift` (requirements §5.4 "lift greater than 1"); the
  co-replenishment and assortment-gap filters use **≥** 1.5 (scenario 4 "lift ≥ 1.5").
- `clean_bills` drops return and voided lines, **whole bills** containing a line above `max_qty_per_line`
  (bulk/wholesale bills), and promotion-day lines when `exclude_promo_days`.
- *(superseded by D-28)* `find_expiry_receivers` allocates the at-risk qty greedily to receivers with the largest sell-before-expiry
  capacity `floor(daily_demand × (days_left − transit_days))` (ties by store id), so a batch may be split.
- `select_supplier`: eligibility uses days from the need's run date to `required_by`; the preferred supplier
  wins if eligible (D-07), else lowest price → shorter lead time → supplier id.
- *(superseded by D-29)* `prioritise_within_budget`: lines ordered HIGH before NORMAL, then ABC A→B→C→unclassified, then store and
  product id; greedily kept while they fit the budget (a line that does not fit is skipped, later smaller lines
  may still fit).
**Changed.** Spec §8 notes.

## D-23 Numeric rules
**Decision.** Products of demand and days are rounded to **6 decimals before `ceil()` / `floor()`**
(e.g. `0.1 × 30 = 3.0000000000000004` must give 3, not 4). Money is `Decimal`, rounded `ROUND_HALF_UP` to
0.01 **only at outputs** (evidence, DTOs, stored values); cost comparisons use unrounded values.
**Changed.** Spec §1.

## D-24 `_priority` signature
**Decision.** `TransferDecisionEngine._priority(state, lead_time_days)` = `"HIGH"` if
`state.days_of_cover < lead_time_days` else `"NORMAL"` (SD-07). CD-3 corrected to match.
**Changed.** CD-3.

## D-25 Property-based tests for the transfer engine
**Decision.** `hypothesis` is a dev dependency. `TransferDecisionEngine.decide` is property-tested for:
no donor ends below its own requirement; for each short store transferred qty + PO qty = need; transfers only
from stores with surplus > 0; no transfers when no store has surplus; shuffled store order gives identical
results (and, for the two-pass agent step, shuffled product order).
**Changed.** CLAUDE.md test conventions unchanged; tests in `backend/tests/unit/tools/`.

## D-26 pandas 3.1 with mlxtend
**Finding.** mlxtend 0.25 `fpgrowth` + `association_rules(num_itemsets=…)` run on pandas 3.1 without warnings.
No pin needed.

---

## D-27 Bulk-bill limit per category
**Decision.** Approves the D-22 bulk-bill rule (a line above the limit drops the whole bill) and makes the limit
configurable per category: business rules `basket.max_qty_per_line` (default 24) and
`basket.max_qty_per_line_by_category` (e.g. `{"rice": 50}`). Lines without a category use the default.
**Changed.** Spec §8, §9; `BasketQualityRules.max_qty_per_line_by_category`.

## D-28 Expiry receivers: single receiver first, only when worth it
**Decision.** Replaces the D-22 greedy allocation. `find_expiry_receivers(…, unit_cost)`:
1. Prefer a **single receiver** whose sell-before-expiry capacity covers the whole at-risk qty (cheapest transfer,
   then shorter transit, then store id).
2. **Split only if no single store can** absorb it: largest capacity first.
3. A transfer is proposed only if `transfer_incremental_cost < qty × unit_cost` (the value of the stock it saves;
   for a split, each part is checked with its own qty). Otherwise the batch goes to markdown / EXPIRY_ALERT.
**Changed.** Spec §8; SD-08.

## D-29 Budget trimming reduces before skipping
**Decision.** Replaces the D-22 skip rule. `prioritise_within_budget(po, budget) → BudgetTrimResult(po, reduced,
skipped)`. Lines are attempted HIGH first, then ABC A→B→C→unclassified, then store and product id. A line that
does not fit is **reduced** to the largest pack-rounded qty ≥ MOQ (or exactly the MOQ) that fits the remaining
budget; if none fits it is **skipped**, and the PO Agent creates a `Recommendation(REORDER, status NEEDS_REVIEW)`
with reason `BUDGET` for each skipped line. The PO is flagged `BUDGET_TRIMMED` when anything was reduced or skipped.
**Changed.** Spec §8; SD-09.

---

## D-30 Baseline forecast excludes stockout days
**Decision.** `ForecastTools.baseline_avg_daily` averages **in-stock days only** within the last `window_days`.
Stockout days use the D-21 definition — closing on-hand = 0, whether the day opened with stock and sold out
(censored demand) or was out of stock all day — and are excluded, so stockouts do not pull the forecast down.
Input gains an optional boolean `is_stockout` column (absent → every day in stock); output gains `in_stock_days`.
With no in-stock day in the window the demand is 0.0 (the agent marks such forecasts LOW confidence).
In the synthetic data, scenario products have constant daily demand in their last 28 days and no stockout days,
so the planted demand equals the baseline exactly (one documented exception: Store C in scenario 3 must hold 0,
so its last day closes at 0 — a stockout day — and is excluded; the remaining 27 days give the same constant).
**Changed.** Spec §1, §8; SD-04.

---

## D-31 FEFO at-risk formula counts only units actually sold (approved 2026-11-04)
**Finding (Phase 4a FEFO check).** The synthetic stock simulator depletes batches strictly FEFO and writes off
whatever is left at expiry. Cross-checking its write-offs against `FreshnessTools.at_risk_by_batch` showed that
the spec §1 formula overstates the risk of later batches whenever an earlier batch expires unsold: it adds the
earlier batch's **full** qty to `qty_ahead`, but the expired units never consume selling days.
Example (1 unit/day; batches 15 @ day 4, 20 @ day 8, 25 @ day 12): spec predicts 11 / 20 / 25 at risk;
actual FEFO write-offs are 11 / 16 / 21.
**Proposal.** `qty_ahead += batch.qty − at_risk` (only the units that sell). Matches the simulator for every
tested demand rate. Scenario 5 is unaffected (single batch). Until approved, the spec formula stays and the
cross-check test is a strict xfail referencing this entry.
**Approved 2026-11-04.** Implemented in `FreshnessTools.at_risk_by_batch`; spec §1 and SD-08 updated; the
simulator cross-check now passes at every tested rate, plus a unit test of the 11 / 16 / 21 example.

---

## D-32 Contract-first API, paging and store scoping in the DTOs (Phase 7)
**Decision (approved).** The `/api/v1` request/response shapes are defined now as Pydantic DTOs
(`app/domain/schemas/{common,dtos}.py`) and registered as routes that return **501 `NOT_IMPLEMENTED`** (standard
error body) until Phase 6. The frontend generates its types from them (`npm run gen:api`) and runs on a typed mock
client (`VITE_USE_MOCKS=true`). Two guards keep the contract in sync: backend test
`tests/unit/test_contract.py::test_frontend_openapi_json_is_up_to_date` (openapi.json vs the FastAPI app) and
`npm run check:api` (schema.d.ts vs openapi.json).
- **Paging (approved).** Every list endpoint takes `page` (≥ 1, default 1), `page_size` (1–200, default 25),
  `sort` (`field` or `-field`), `q` (free text) plus endpoint filters, and returns `Page[T]`
  `{items, total, page, page_size}`. DataTable pages and sorts on the server.
- **Store scoping in the DTOs (approved).** A Store Supervisor sees another store only as `Counterpart`
  `{store: {store_id, name}, qty}`. DTOs forbid unknown fields. Fields that describe another store's stock are
  nullable and filled for the Super Admin only: `TransferEvidenceDTO.donor_surplus`,
  `.donor_protected_requirement`. A consolidated PO shows a supervisor only their own lines plus
  `other_store_lines: [Counterpart]`. A supervisor asking for another store's data gets 403.

**Confirmed 2026-11-04 with one change — scoping is per viewer:** the donor store's own supervisor sees its own
surplus and protected requirement (it is their stock and they approve its release); the destination supervisor
sees name + quantity plus a numberless assurance `donor_keeps_requirement` ("Donor keeps its full requirement");
the Super Admin sees everything. Transfer costs visible to both roles; rank sorting is a Phase 6 requirement
(spec §5); `GET /runs/latest` is in spec §5.

**Implementation choices (as proposed).**
- Design doc §6 lists "donor surplus" and "donor protected requirement" on the recommendation detail, while CLAUDE.md
  rule 10 limits supervisors to name + quantity. Resolution: the rule wins for supervisors (fields null), the Super
  Admin sees them.
- Transfer cost and the transfer-vs-PO incremental cost are visible to **both** roles (they are not another store's
  stock data, and §6 requires the comparison on the detail screen).
- `sort` on `priority` and `stockout_risk` ranks by business meaning (HIGH > NORMAL; HIGH > MEDIUM > LOW), not
  alphabetically; the Phase 6 queries must do the same.
- New endpoint `GET /runs/latest` (RunInfoDTO) for "Data as of last run" — `GET /agent-runs` is Super Admin only.
- New error code `NOT_IMPLEMENTED` (501) for the contract stubs; operation ids are handler names
  (e.g. `list_recommendations`).
**Changed.** Spec §5; backend `app/api/routers/contract.py`; frontend `src/api`, `src/mocks`.

---

## D-33 Design System v1.1 — contrast fixes (approved 2026-11-04)
**Decision.** Token values changed after measurement against WCAG AA 4.5:1 (docs/notes/contrast-proposal.md),
versioned as Design System **v1.1** (the frozen v1.0 is not edited silently):
`--warning-text` #986F28 → #8C6625 (4.64:1), `--attention-text` #A7653D → #995C38 (4.63:1),
`--info-text` #56758F → #516F87 (4.60:1, used by "Pending" / "Due in" badges).
`--text-muted` (#958B8D, 3.06–3.30:1) is **retired for text** and kept for decorative, non-text use only
(Tailwind `decor`, e.g. `border-decor`); essential small text uses `--text-secondary`.
`npm run check:no-hex` fails on hex colours outside tokens.css and on any text use of `--text-muted`.
**Changed.** frontend/src/styles/tokens.css, index.css; docs/03-design-system.md (v1.1 note, §1, §8);
frontend/scripts/check-no-hex.mjs.

---

## D-34 Phase 8a contract additions and mock data (approved 2026-11-04)
**Decision.**
- **Evidence is a discriminated union** on `kind` — one Pydantic model per kind, so each has exactly its own fields
  and TypeScript narrows on it: `TRANSFER` (surplus or expiry-aware, with `expiring_batch`), `REORDER`,
  `CO_REPLENISH`, `EXPIRY` (EXPIRY_ALERT / MARKDOWN), `ASSORTMENT_GAP`, `NEEDS_REVIEW`
  (reason `LOW_CONFIDENCE | BUDGET | NO_ELIGIBLE_SUPPLIER`). `kind` is required. NEEDS_REVIEW is a recommendation
  *status*, so the union is keyed on `kind`, not `rec_type`. `RecommendationDetailDTO.reason` is replaced by the
  reason inside each evidence kind.
- **Inventory endpoints:** `GET /stores/{id}/inventory` returns `StoreInventoryPage` (Page + store + store-wide
  `summary` counts, SD-15 totals) and takes `refill_only`; new `…/inventory/movements` (type, from, to, product_id),
  `…/inventory/batches` (product_id; FEFO rank and at-risk qty per batch) and `…/inventory/expiring` (within_days).
  `GET /recommendations` and `GET /transfers` take `product_id`; recommendations also `priority`.
- **Super Admin inventory store:** picker when "All stores" is selected, defaulting to the last store chosen
  (per-browser preference).
- **Mock data** is exported from the synthetic `small` dataset by `backend/scripts/export_mock_fixtures.py`, which
  runs the real Phase 3 tools in nightly-run order, validates every object against the DTOs and asserts the five
  scenarios. A backend test fails if the committed fixture is stale. The fixture is a lazily loaded chunk that is
  never part of a production build.

**Implementation choices (to confirm).**
- Synthetic data fixes found by running the planner on the fixtures: paneer shelf life 14 days with **near-dated
  supply** for the scenario-5 donor store (every delivery arrives with the same remaining life, so FEFO order holds),
  and bread shelf life 14 days ("long-life packaged"). With the shorter shelf lives, Stores B/C held more than they
  could sell before expiry (their requirement window is 9 days), which produced expiry alerts and extra transfers
  around scenarios 4–5.
- Lost revenue of 0 is sent as null (shown as "—"), not ₹0.00.
- 4xx API answers are not retried by the client (they will not change); 5xx/network errors are retried once.
- The synthetic data has no NEEDS_REVIEW (the planted stale SKU is not short) and no ASSORTMENT_GAP (all products
  are listed in every store); those evidence views are covered by component tests with typed examples.
**Changed.** Spec §5; backend DTOs and contract routes; frontend api/mocks/pages; data/synthetic scenarios.

---

## D-35 Phase 2 schema decisions (approved 2026-11-04)
**Decision.**
1. **Status columns** are `text` + `CHECK (status IN (…))`, not native PostgreSQL enum types; Python uses one
   `StrEnum` per status (`app/domain/models/enums.py`). Adding a value (as `SUPERSEDED` was) is a one-line
   migration.
2. **Partitions:** `sales_line` and `inventory_movement` monthly from 2026-01 to 2027-12 plus a `DEFAULT`
   partition. **Phase 5 must add a job that creates future monthly partitions before data reaches the default
   partition** (and alerts if the default partition holds rows).
3. **Dashboard view scope:** `mv_dashboard_store_day` holds calendar-day figures only (revenue, gross profit, units,
   stockout share). Lost revenue/profit, near-expiry value and pending counts belong to a nightly run and are read
   from the run tables and `mv_inbox_counts`. SD-11 updated to v3.1.
4. **Seed split:** BusinessRule defaults (spec §9) in migration `0002`; stores A/B/C (the generator's fixed UUIDv5
   ids) and the PoC users in the idempotent `python -m scripts.seed`, password from `SEED_USER_PASSWORD`,
   defaulting to `demo` only when `APP_ENV=local`. Passwords never appear in migrations.
5. **`business_rule` key:** surrogate PK `rule_id` + `UNIQUE NULLS NOT DISTINCT (rule_key, scope_store_id)`
   (PostgreSQL 15+), so one global row and at most one override per store.
6. **Columns the contract and diagrams need:** `recommendation.priority`, `.reason`, `.lost_profit` (plus the
   generated `priority_rank` for the indexed rank sort); `app_user.username`, `.password_hash`, `.is_active`;
   `supplier.is_active`; `store.code`; `batch.received_date`; `agent_run.run_date`; `tool_call.status` gains `WARN`
   (SD-02); `decision_evidence.rec_id` nullable (SD-02 logs evidence without a recommendation).
   **Nightly-run idempotency guard (changed on approval):** partial unique index
   `agent_run (run_date) WHERE agent_name = 'nightly' AND status IN ('RUNNING','SUCCESS','PARTIAL')` — a FAILED
   run can be re-run for the same date; a second running or completed run cannot be started.
**Changed.** Spec §10; CD-1 v3.2, CD-2 v3.2, SD-11 v3.1; PROMPTS.md Phase 5.

---

## D-36 Async API database access, separate worker engine, connection budget (approved 2026-11-04)
**Decision.** `app/core/db.py` builds two engines:
- **API:** async SQLAlchemy over psycopg 3 (`create_async_engine("postgresql+psycopg://…")`), `pool_size` 10,
  `max_overflow` 10, `pool_pre_ping`, `pool_recycle` 1800 s, `pool_timeout` 5 s, server-side
  `statement_timeout` **5 s** (API engine only), `async_sessionmaker(expire_on_commit=False)`.
- **Celery / Alembic:** a separate sync engine with its own pool (2 + 3 overflow per worker process) and its own
  `statement_timeout`, default **10 minutes**, so the nightly run and the MV refresh are not cut off.
- **Connection budget** (spec §11): `api_workers × (pool_size + max_overflow) + celery_processes ×
  (worker pool + overflow) + headroom` must stay below PostgreSQL `max_connections` (default 100). PgBouncer
  (transaction mode, prepared statements off) is the production option.
psycopg 3 already provides the async driver; SQLAlchemy's asyncio layer needs `greenlet`, added through the
`sqlalchemy[asyncio]` extra (correction found in Phase 2: the plan had said "no new dependency").
**Changed.** Spec §11; `app/core/db.py`, `app/core/config.py`, `/health` (Phase 2).

---

## D-37 Cursor paging for unbounded ledgers; movement time columns (approved 2026-11-04)
**Decision.**
- Bounded lists keep offset paging (`Page[T]`, D-32). Unbounded, append-only tables use keyset paging:
  `CursorPage[T] = {items, next_cursor, page_size}` with request `cursor` + `page_size` and **no `total`**.
  Now: `GET /stores/{id}/inventory/movements`; later audit, tool-call, notification and run-history lists.
- **`inventory_movement` gets `occurred_at`** (timestamptz, when the stock moved) and **`business_date`** (store
  trading day, IST). The table is partitioned, indexed and cursor-paged on `occurred_at`; `created_at` is
  insert/audit time only. PK `(movement_id, occurred_at)`. Phase 4b backfill writes the historical `occurred_at`.
- The cursor is opaque (base64url of `(occurred_at, movement_id)`), order `occurred_at DESC, movement_id DESC`;
  `next_cursor` null on the last page; malformed cursor → 422 `VALIDATION`. `from`/`to` filter `business_date`
  and are also converted to an `occurred_at` range for partition pruning.
**Changed.** Spec §3, §5, §10, §11; CD-1 v3.2; DTOs (`CursorPage`, `CursorParams`), contract route, openapi.json,
frontend generated types and mock client.

---

## D-38 Indexes for the real query patterns (approved 2026-11-04)
**Decision.** Every list/detail query has an index matching its filter and order (spec §10 table), including
partial indexes for PENDING recommendations and PENDING PO lines, active transfers, unread notifications and
batches with stock, and a `pg_trgm` GIN index on product name and SKU for `q` search (extension enabled in
migration `0001`). Indexes on partitioned tables are **created on the parent table** so every future partition
inherits them; a test creates a new partition and checks its indexes. At the end of Phase 4b the top-10 queries
are run with `EXPLAIN (ANALYZE, BUFFERS)` against the `full` synthetic dataset and the plans are recorded in
`docs/notes/query-plans.md`.

---

## D-39 No N+1 queries (approved 2026-11-04)
**Decision.** ORM relationships default to `lazy="raise"`, so an implicit lazy load fails instead of issuing a
hidden query; repositories load related rows explicitly (`selectinload` for collections, `joinedload` for
many-to-one). A `count_queries` test fixture (SQLAlchemy `before_cursor_execute`) is built in Phase 2; Phase 6
adds, per list endpoint, an integration test asserting the query count does not grow with the number of rows.

---

## D-40 Response serialisation, compression, column selection (approved 2026-11-04)
**Decision.** Responses are serialised by Pydantic through the declared response model / return type (FastAPI
writes JSON bytes on the Rust side). **No `ORJSONResponse` / `orjson`** — FastAPI marks them deprecated because
the response-model path is faster. A test fails if any route lacks a response model. `GZipMiddleware
(minimum_size=1000)` is added. List queries select only the columns the DTO needs.
*(Replaces the original request "ORJSONResponse", agreed 2026-11-04.)*

---

## D-41 Bulk loads with COPY (approved 2026-11-04)
**Decision.** Phase 4b ingestion loads sales lines, movements and snapshots with PostgreSQL `COPY` (psycopg
`cursor.copy`) into staging tables, then `INSERT … SELECT` into the partitioned tables, one transaction per file.
Row-by-row ORM inserts are not used for bulk data.

---

## D-42 Performance budgets (approved 2026-11-04)
**Decision.** p95 < 200 ms for cached reads and < 500 ms for uncached reads, verified by a k6 or Locust load test
in Phase 9 (tool chosen then). The nightly-run time limit on the `full` dataset is **measured in Phase 5** and
then proposed for approval; it is recorded in spec §11.

---

## D-43 Phase 2 schema details beyond D-35 (to confirm)
**Decision (implemented in migration 0001; confirm or tell me to change).** Found while building the models from
CD-1/CD-2 against the sequence diagrams and the synthetic data:
- **`sales_line.is_return`, `.is_voided`, `.is_promo_day`** (bool, default false): SD-05 `clean_bills` drops returns
  and voided lines and optionally promotion days (requirements §6, D-27), and the synthetic data carries these flags,
  but CD-1 had no columns for them. `mv_dashboard_store_day` uses them: revenue = sale lines (qty × price − discount)
  − returns (qty × price); voided lines count nothing; gross profit uses the product's current cost price.
- **`sales_transaction.txn_date`** — the IST business day of the bill (the synthetic data has it; avoids
  timezone arithmetic in daily queries).
- **`association_rule.run_id`** (FK agent_run) — CD-1's note says every planning output references the run that
  produced it; the class itself lacked the column.
- **Integrity checks** (no business rule changed): a Store Supervisor must have a store; a notification needs an
  audience (role, store or user); transfers and routes need two different stores; quantities that cannot be
  negative (`qty`, `received_qty`, `moq`, `pack_size`) are checked.
- **`llm_usage.est_cost`** is NUMERIC(14,6): provider cost estimates are fractions of a cent (not ₹ money).
- **`kpi_snapshot.value`** is NUMERIC(18,4): it stores rates as well as amounts.
**Changed.** CD-1 v3.2, spec §10, migration 0001.

---

## D-44 LLM provider: Groq with OpenAI open-weight models (approved 2026-11-04)
**Decision (product owner: "use any model of OpenAI which is useful for our use case from Groq API").** The
explanation text is generated through Groq's OpenAI-compatible chat API. This replaces the Anthropic SDK named in
CLAUDE.md's fixed stack; rule 11 is unchanged (the LLM only writes text, all numbers come from the evidence).
- **Models:** `openai/gpt-oss-120b` (primary) and `openai/gpt-oss-20b` (fallback on errors, timeouts, rate
  limits). Both are Groq *production* models (console.groq.com/docs/models, checked 2026-11-04); preview models
  (e.g. the earlier `qwen/qwen3.8-27b` fallback) are not used because Groq says they can be withdrawn at short
  notice. 120b is chosen because the text must restate exact figures and stay grounded; at about $0.15 / $0.60
  per 1M input / output tokens a 3-item batch measured ~950 tokens, about $0.0003, in 1.3 s.
- **Request:** strict `json_schema` response format (constrained decoding on gpt-oss), `reasoning_effort` low,
  `include_reasoning` false, temperature 0 (spec), `max_completion_tokens` 4096 (reasoning counts toward it), one
  retry on 429/5xx honouring Retry-After, then the fallback model. A truncated answer (`finish_reason` ≠ stop) is
  an error, never partial text.
- **Batching:** `llm_batch_size` (20) items per call.
- **Grounding:** facts sent to the model exclude ids and the donor-stock fields another store's supervisor must not
  see (rule 10, D-32); keys and enum values are sent as words. A text is accepted only if every number in it is a
  fact number (₹1,250 = 1,250 = 1250.00; Indian lakh grouping accepted) and it contains no field name; otherwise
  that item uses its deterministic template. Templates now state only facts present in the evidence (missing
  values are omitted, not shown as 0).
- **Telemetry:** each call writes `llm_usage` (model, tokens, est_cost). The earlier logger passed wrong column
  names and silently logged nothing; fixed.
- `httpx` moved from dev to runtime dependencies (app code imports it). `LLM_PROVIDER=template` disables the LLM.
  The `anthropic` package is no longer imported — removal pending the owner's OK (dependency change).
**Changed.** CLAUDE.md stack; spec §8; `.env.example`; `app/services/{llm_client,explanation_service}.py`;
`app/core/config.py`; observability repo; tests `tests/unit/services/test_explanation_service.py`.

---

## D-45 Forecast models (ETS, Croston-SBA, TSB) — built, measured, off by default (2026-11-04)
**Decision (product owner: "feel free to use any ML model also in required places").** The place the spec reserves
for models is SD-04's forecast extension. `statsforecast` (named by the spec) requires pandas < 3 and the project
runs pandas 3.1, so the models are implemented as pure, tested numpy tool functions instead — no new dependency:
- **ETS(A,N,N)** (simple exponential smoothing, α from {0.05, 0.1, 0.2, 0.3, 0.5} by in-sample one-step error) for
  smooth demand (ADI < 1.32); **Croston with the Syntetos-Boylan correction** and **TSB** (decays when demand
  stops) for intermittent demand. Stockout days are dropped before fitting (D-30).
- **Selection:** rolling-origin backtest (3 windows of `forecast_horizon_days`, at least `min_history_days` (56)
  in-stock days) scored by WMAPE of the horizon total; a model replaces the baseline only if it is > 5% better.
- **Measured** with the rewritten 28-day replay (`scripts/replay_evaluation.py`, full profile): baseline WMAPE
  17.7% (bias +0.2%), model selection 18.5% (bias +1.1%); need-flag accuracy 89.6% vs 89.1%. A sweep of the
  backtest horizon (7, 14) and threshold (5–30%) never beat the baseline: the synthetic demand is a stable level
  with weekly seasonality and spikes, which the 28-day in-stock mean already estimates.
- **Therefore `RunParams.use_model_selection = False`.** The models stay available and tested; switch on when a
  replay on real POS data shows a gain. Possible next step if wanted: a day-of-week profile for windows that are
  not whole weeks.
**Also fixed (found while integrating):** the forecasting agent read one row per *bill line* without grouping,
over sale days only — the "daily demand" was the mean line quantity (≈ 1) and ignored zero days. It now uses daily
totals, zero-filled across the lookback, with stockout days flagged (`daily_series`, regression test). The planted
scenarios sell every day in single lines of constant size, which is why the old scenario tests did not catch it.
ABC/XYZ is written with one bulk UPDATE instead of one SELECT per store-SKU.
**Evaluation report:** `docs/EVALUATION_REPORT.md` is now generated by the script; every figure is computed (the
previous version contained typed-in numbers).
**Changed.** `app/tools/forecast.py`, `app/agents/forecasting.py`, `app/agents/base.py`, spec §8,
`scripts/replay_evaluation.py`, `docs/EVALUATION_REPORT.md`; tests `test_forecast_models.py`,
`test_replay_evaluation.py`.

---

## D-46 Dashboard data from the API only; stock-out risk rule; rule-1 requirement on the inventory screen (2026-11-04)
**Decision.** Every dashboard figure comes from the API; a widget without data shows an empty state.
- **New endpoint `GET /dashboard/insights?store_id&period`** → `DashboardInsights`: daily sales units/revenue,
  Σ forecast daily demand of the latest run, inventory value by category (on hand × cost), shelf vs backroom value,
  stock health, units/value expiring in the next 14 days, POs by status (value of the viewer's lines), and per-store
  performance (Super Admin, all stores). Cached like `/dashboard` (key prefix `dashi`).
- **Stock-out risk (formalises the Phase 8a rule):** `days_of_cover = available / max(d, 0.01)`; **HIGH** if cover <
  lead time of the supplier serving that store, **MEDIUM** if < lead + review period, else **LOW**
  (`RequirementCalculator.stockout_risk`). Used by the dashboard and the inventory screen.
- **Periods end on the data day** (latest run date − 1, the last day of history), not on the run date.
- **Fixes found:** the dashboard service queried `inventory_position.on_hand` and
  `mv_inbox_counts.active_transfers_destination` (neither exists) inside `except Exception: pass`, so it returned
  zeros and the page showed typed-in sample figures ("₹42.8L", "148", …) and a sample store name. Query errors now
  propagate; only Redis is fail-open. Movers exclude returns. The inventory screen computed the own requirement with a
  hard-coded 2-day lead time, no min display qty and 5 units/day when no forecast existed — it now uses rule 1
  (`own_requirement` with the lead time of the supplier serving that store) and the latest run's forecasts only.
- **UI:** the dashboard page no longer has a client-side role switcher (role comes from the signed-in user) nor
  hidden screen-reader text added to satisfy old tests. Mock fixtures now include insights computed from the
  synthetic data with the same definitions.
**Changed.** Spec §5 (new route); DTOs; `dashboard_service.py`; `inventory_view_service.py`;
`app/tools/requirement.py`; frontend Dashboard page, API client, mock; tests (backend integration, frontend).

---

## D-47 The five demo scenarios through the real pipeline (2026-11-04)
**Decision / fixes.** Phase 5's acceptance ("the pipeline on synthetic data asserts the outcomes of scenarios 1–5")
was not met: the scenario tests used hand-made rows and asserted only that rows existed. Now
`tests/scenarios/test_demo_scenarios.py` bulk-loads the small synthetic dataset, runs the orchestrator and asserts
every planted outcome from the manifest, D-34 evidence on every recommendation, the planted mismatch and stale SKU,
and per-viewer scoping through the HTTP API. Fixes needed to get there:
- **Synthetic loader** (`app/services/synthetic_loader.py`, COPY, D-41): master data, bills, lines, snapshots and the
  ledger (opening balance, daily SALE totals, PO_RECEIPT, EXPIRY_WRITE_OFF, reconciliation ADJUSTMENT only where the
  replay differs — exactly the planted mismatch). Position = last snapshot = Σ movements; incoming = open orders.
- **Orchestrator:** ingests `run_date − 1` (it ingested the run date itself, which has no data); ingestion is
  idempotent per store-day; the already-running guard is per run date.
- **Nothing committed the nightly run** (Celery task, `run_agents`, the UI trigger) — every run was rolled back.
  Callers now commit, including a FAILED status. Default run date = day after the latest loaded POS day.
- **RunParams.load** reads the BusinessRule table (it returned code defaults; e.g. stale_days was 30, not 3).
- **Stock balancing** rewritten on shared `PlanningInputs`: available includes `incoming` (rule 1); cost inputs from
  business rules (were hard-coded 200 / 0.001 / 0.05); urgency order and D-17 planned deliveries; LOW confidence →
  NEEDS_REVIEW; **co-replenishment** only for a product reordered in the SAME store, this run's rules, lift ≥
  co_replenish.min_lift, ≤ limit, supplier already delivering (it used any store's reorders and a 3-day lead time).
- **Freshness** uses real receiver states (requirement was 0) and D-34 evidence; **related products** cleans bills
  and uses the basket business rules (min_bills was 10, confidence 0.1); **purchase orders** check supplier
  eligibility with the lead time of that supplier for that store (58 needs were wrongly "no eligible supplier"),
  and move the existing recommendation to NEEDS_REVIEW instead of creating a duplicate.
- **Evidence:** every agent writes the D-34 union (validated DTO) to the recommendation and `decision_evidence`; the
  detail endpoint no longer hides invalid evidence; a donor store's supervisor may open a transfer it donates to
  (D-32); `/agent-runs` is Super Admin only.
- **Schema:** `supplier_product.moq` may be 0 (= no minimum; migration 0003). **Security:** outside local/test the
  JWT secret must not be the default and must be ≥ 32 bytes.
- **Demo:** `seed_demo` = generate + load + users + real nightly run; `reset_demo` keeps the global business rules
  (TRUNCATE … CASCADE had emptied them). The demo uses the **small** profile: in the full profile (500 bills/day) the
  planted bread→butter pair has support 0.0039 < `basket.min_support` 0.005, so scenario 4's co-replenishment does
  not appear — the business rule is not changed to suit the demo.
- **Measured (D-42):** full profile — load 81 s; agents ≈ 25 s; explanations ≈ 4.7 min (22 Groq batches, rate
  limits → fallback model); small profile end to end 57 s. **Proposed nightly limit: 15 minutes** on the full
  dataset with the LLM (≈ 2 minutes without it).

---

## D-48 Analytics and Settings on real data; business-rules API (2026-11-04)
**Decision.**
- **`GET /analytics`** (supervisors: own store): ABC-XYZ counts of listed store-SKUs, revenue / gross profit / margin /
  units by category for the period, forecast method × confidence mix of the latest run, top-10 lost sales (revenue
  and profit separately, rule 9). The Analytics page shows only these; the previous page was entirely sample data
  (and a "forecast accuracy trajectory" with no data behind it — real accuracy is in docs/EVALUATION_REPORT.md).
- **`GET /admin/business-rules`, `PUT /admin/business-rules/{key}`** (Super Admin, spec §5): a registry of the 22
  editable global rules with type, range and allowed values; `basket.*` / `co_replenish.*` are dotted keys. Money is
  stored as a 2-decimal string, rates as exact decimal strings. Invalid values → 422 with the field; unknown key →
  404. Changes apply from the next nightly run (RunParams.load). Per-store overrides are not offered: nothing reads
  them yet.
- **Settings page:** the Super Admin edits exactly these rules (one at a time); a supervisor sees a read-only
  profile. The previous page showed invented values (e.g. holding cost 0.05 vs the rule's 0.0005, a "service level
  target" and a 16:00 cut-off that are not business rules) and "saved" only to local state.
- **Cleanup:** the unmounted contract-stub router was deleted; the unused `anthropic` dependency removed (D-44);
  pages no longer add a second `<h1>` under the shell's title.
**Changed.** Spec §5; `app/services/{analytics_service,business_rule_service}.py`; routers; DTOs; mock fixtures
(computed from the synthetic data); frontend Analytics / Settings pages, client, hooks, tests.
