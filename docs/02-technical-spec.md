# RetailPilot AI — Technical Specification (implementation reference)

Derived from business requirements v2.2, diagrams v3 (`docs/diagrams/`) and the decision log
(`docs/05-decision-log.md`, D-01 … D-17). Use these names, formulas and states exactly. Values marked
**(confirm)** are placeholder defaults stored in `BusinessRule` — never hard-code them.

## 1. Core formulas

```
serving supplier     = store_product.preferred_supplier_id                                   (D-07)
lead_time_days       = SupplierStoreTerms.lead_time_days → SupplierProduct.lead_time_days
                       → Supplier.default_lead_time_days   (first one defined, for the serving supplier)
demand_window_days   = lead_time_days(store's supplier) + review_period_days
own_requirement      = ceil(daily_demand × demand_window_days)
                       + ceil(daily_demand × safety_stock_days)
                       + min_display_qty
on_hand              = shelf_qty + backroom_qty
available            = shelf_qty + backroom_qty + incoming − reserved
   in planning (nightly run) incoming = non-overdue incoming + on_order_pending   (D-14, D-16):
     overdue incoming   = incoming whose expected date + incoming_overdue_grace_days < run_date — NOT counted
                          (expected date: PO submitted date + lead time; transfer dispatched date + transit_days)
     on_order_pending   = qty of PENDING / ESCALATED lines on PENDING_L1 POs kept from earlier runs
surplus              = available − own_requirement          (≤ 0 → not a donor)
need (short store)   = own_requirement − available          (> 0 → short)
days_of_cover        = available / max(daily_demand, 0.01)

transfer_incremental_cost = fixed_cost + per_unit_cost × qty + handling_cost_per_unit × qty
po_incremental_cost       = order_fixed_share + delivery_charge_share
                          + qty × unit_cost × holding_cost_rate_per_day × days_to_sell_at_donor
                          + qty × unit_cost × expiry_risk_pct            (perishables only)
   where purchase price itself is NOT included
   order_fixed_share, delivery_charge_share (marginal, D-10, D-17)
                          = 0 if (supplier, store) is marked as receiving a PO this cycle,
                            else order_fixed_cost and SupplierStoreTerms.delivery_charge in full
   marking is two-pass (D-17): pass 1 marks (serving supplier, short store) for every product where no store
   has surplus; pass 2 decides the other products, short stores by days_of_cover ascending (ties: store_id),
   products by their most urgent store, and marks each pair that gets a PO need — deterministic
   days_to_sell_at_donor  = min(qty / donor.daily_demand, cap)  ; = cap when donor.daily_demand = 0
                            cap = product.shelf_life_days, or 90 if the product has no shelf life
   perishable             = shelf_life_days ≤ perishable_max_shelf_life_days (default 30)
transfer chosen if  transfer_incremental_cost < po_incremental_cost
                AND route.transit_days ≤ lead_time_days of the short store's supplier
                AND donor stays ≥ own_requirement after the transfer (donor protection)
low confidence (D-04): a store-SKU whose forecast confidence = LOW is neither donor nor receiver; if short it
                gets Recommendation(REORDER, status NEEDS_REVIEW) and NO ReplenishmentNeed

co-replenishment (D-02): complement C of reordered product P in store S qualifies when
   available(C) − daily_demand(C) × review_period_days(C) < own_requirement(C)
   AND C's serving supplier for S is already delivering to the SAME store S this cycle
       (a SHORTFALL need exists for (supplier, S) — delivery charge is per store, D-13)
   qty = max(1, ceil(own_requirement(C) − (available(C) − daily_demand(C) × review_period_days(C))))
   if C already has a need in S this run → set linked_product_id = P and lift on it; never add a second need

incoming  (D-03) = Σ qty of transfers to the store in DEST_ACCEPTED | DONOR_APPROVED | DISPATCHED
                 + Σ open qty of PO lines APPROVED | EDITED on POs APPROVED | SUBMITTED (until goods receipt)
reserved  (D-03) = Σ qty of transfers from the store in DEST_ACCEPTED | DONOR_APPROVED (soft reservation)

numeric rules (D-23): demand × days is rounded to 6 decimals before ceil()/floor();
   money is Decimal, ROUND_HALF_UP to 0.01 only at outputs; cost comparisons use unrounded values

stockout day (D-21) = closing_on_hand = 0 (includes days that opened with stock and sold out — censored demand)
demand rate          = mean daily units over in-stock days (zero-sale in-stock days included; stockout days excluded)
lost_units   = demand rate on in-stock days × stockout_days     (confidence LOW if in-stock days < 7)
lost_revenue = lost_units × selling_price
lost_profit  = lost_units × (selling_price − cost_price)

PO qty rounding = max(moq, ceil(qty / order_pack_size) × order_pack_size)
required_level  = "L2" if po.total_value ≥ po_l2_threshold else "L1"
forecast horizon = max over store-SKUs of (lead + review + safety), never below horizon_days
```

Worked example (must be a unit test): Store C need 40, holds 0; Store A available 54, requirement 30
(surplus 24); Store B surplus 0 → `TransferProposal(A→C, 24)` + `PONeed(C, 16, "PARTIAL_SURPLUS")`.

FEFO at-risk qty per batch (earliest expiry first): `sellable = daily_demand × days_left − qty_ahead`;
`at_risk = max(0, batch.qty − max(0, floor(sellable)))`; `qty_ahead += batch.qty`.

## 2. State machines

**PurchaseOrder.status**: `DRAFT → NEEDS_REVIEW | PENDING_L1 → (PENDING_L2 | APPROVED | REJECTED | SPLIT) ;
PENDING_L2 → APPROVED | REJECTED ; APPROVED → SUBMITTED → RECEIVED`. `SPLIT` = parent closed, child PO continues.
`NEEDS_REVIEW → PENDING_L1 | REJECTED` via `POST /purchase-orders/{po_id}/resolve` (Super Admin, D-08).
`PENDING_L1 → SUPERSEDED` when the next nightly run replaces a PO none of whose lines were decided (D-03).
`SUBMITTED → RECEIVED` when every continuing line is fully received (SD-16); partial receipts keep `SUBMITTED`.
`SUBMITTED → RECEIVED` also by **close short** (Super Admin, `POST /purchase-orders/{po_id}/close-short`, Phase 6,
D-16): undelivered qty stops counting as incoming; short qty recorded per line (`short_closed_qty`).
A PO kept from an earlier run (some line decided) keeps its `PENDING`/`ESCALATED` lines; they count as
`on_order_pending` in the next run (D-14).

**POLine.line_status**: `PENDING → APPROVED | EDITED | REJECTED | ESCALATED | EXPIRED | SUPERSEDED`;
`ESCALATED → APPROVED | EDITED | REJECTED` (Super Admin, recorded as L1 on behalf of the store, D-01).
L1 is finalised when **no line is PENDING or ESCALATED** (D-01), or at the deadline with `deadline_action = EXPIRE`
(SD-14). Approved/edited lines continue; if any line is rejected/expired, approved lines move to a child PO
(`parent_po_id`). L2 threshold uses the continuing PO's value. `POLine.received_qty` tracks goods receipt.

**TransferOrder.status**: `PROPOSED → DEST_ACCEPTED → DONOR_APPROVED → DISPATCHED → RECEIVED`;
`PROPOSED → REJECTED` (destination declines); `DEST_ACCEPTED → REJECTED` (donor declines, reason required,
destination notified, D-15); `DEST_ACCEPTED → CANCELLED` (surplus gone at re-check; the
need is recalculated by the next nightly run — no carry-forward, D-03); `PROPOSED → SUPERSEDED` (next run, D-03).
Stock effects (D-03): DEST_ACCEPTED → receiver `incoming += qty`, donor `reserved += qty`;
REJECTED/CANCELLED after acceptance → both released; DISPATCHED → donor `reserved −= qty` + `TRANSFER_OUT`;
RECEIVED → receiver `incoming −= qty` + `TRANSFER_IN(received_qty)`.

**Recommendation.status**: `PENDING → ACCEPTED | EDITED | REJECTED | NEEDS_REVIEW | SUPERSEDED`
(`SUPERSEDED` only from `PENDING`, by the next nightly run, D-03).
**AgentRun.status**: `RUNNING → SUCCESS | PARTIAL | FAILED`.

**Run supersession (D-03).** After ingestion and before the first agent, `WorkflowOrchestrator` calls
`RunSupersession.supersede_previous(run_id)`: previous runs' `PENDING` recommendations, `PROPOSED` transfers and
`PENDING_L1` POs with no decided line (and their `PENDING` lines) become `SUPERSEDED`. Items a person has acted on
are kept and their effect on `incoming` / `reserved` is counted by the new run.

## 3. Inventory movement ledger
All stock changes are `InventoryMovement` rows; `InventoryPosition` is a maintained projection.

| movement_type | qty sign | location | created by |
|---|---|---|---|
| SALE | − | SHELF | ingestion (SD-02) |
| PO_RECEIPT | + | BACKROOM | goods receipt (SD-16) |
| TRANSFER_OUT | − | BACKROOM | dispatch (SD-12) |
| TRANSFER_IN | + | BACKROOM | receipt (SD-12) |
| SHELF_REFILL | −backroom / +shelf (pair) | both | store task |
| ADJUSTMENT | ± | either | reconciliation vs POS snapshot (SD-02) |
| EXPIRY_WRITE_OFF | − | either | freshness / store action |

Transit loss (received < sent) is recorded as a discrepancy on the transfer — `expected_qty`, `received_qty`,
`loss_value` on `transfer_order` (D-06) — with no extra movement; both sides are already correct.
`incoming` and `reserved` on `InventoryPosition` are commitments, not stock, so they are maintained by
`TransferService` / `ApprovalService` / `GoodsReceiptService` as listed in §2, not by movements.
Ingestion also writes `inventory_daily_snapshot` (closing stock per store-product-day, D-09); stockout day =
`closing_on_hand = 0`.

## 4. Roles and permissions

| Capability | Store Supervisor | Super Admin |
|---|---|---|
| Data scope | own store only | all stores |
| PO lines L1 (own store) | ✓ PENDING lines, before l1_deadline | ✓ ESCALATED lines (recorded as L1 for that store) |
| PO L2 | – | ✓ |
| Resolve NEEDS_REVIEW PO / close PO short | – | ✓ |
| Transfer reject | ✓ destination (PROPOSED) · donor (DEST_ACCEPTED) | – |
| Goods receipt (PO_RECEIPT) | ✓ own store's lines | view |
| Transfer: accept incoming / approve release / dispatch / receive | ✓ for own store's side | view |
| Business rules, suppliers, stores, users | – | ✓ |
| Agent runs / system monitoring | – | ✓ |
Cross-store rule: a supervisor sees another store only as name + offered/requested quantity.

## 5. API (FastAPI, prefix /api/v1, JWT bearer; all list endpoints paginated)

| Method & path | Handler → service | Diagram |
|---|---|---|
| POST /auth/login | issue JWT (seeded PoC users) | – |
| GET /me | current user, role, store | – |
| GET /stores | stores visible to the user (supervisor: own store only) | – |
| GET /dashboard?store_id&period | DashboardService.get_summary | SD-11 |
| GET /stores/{store_id}/inventory?category&status | StoreInventoryService.get_view (no aisle filter in PoC, D-10) | SD-15 |
| GET /stores/{store_id}/inventory/movements?product_id&type&from&to | ledger tab | – |
| GET /stores/{store_id}/inventory/batches?product_id | batches tab | – |
| GET /stores/{store_id}/inventory/expiring?within_days | expiring-soon tab | – |
| GET /recommendations?store_id&status&type | RecommendationService.list_inbox | – |
| GET /recommendations/{rec_id} | RecommendationService.get_detail (evidence) | – |
| GET /purchase-orders?status&store_id · GET /purchase-orders/{po_id} | PO queries | – |
| POST /purchase-orders/{po_id}/resolve | PurchaseOrderService.resolve_needs_review (Super Admin) | – |
| POST /purchase-orders/{po_id}/receipts | GoodsReceiptService.receive | SD-16 |
| POST /purchase-orders/{po_id}/close-short | PurchaseOrderService.close_short (Super Admin, Phase 6) | – |
| POST /approvals | ApprovalService.decide | SD-10 |
| GET /transfers?store_id&status · GET /transfers/{id} | TransferService queries | – |
| POST /transfers/{id}/accept · /approve-release · /reject · /dispatch · /receive | TransferService | SD-12 |
| GET /notifications?unread · POST /notifications/{id}/read | NotificationService | SD-14 |
| GET /agent-runs · GET /agent-runs/{run_id} | ObservabilityService | – |
| POST /admin/runs (trigger nightly run manually, Super Admin) | nightly_run_task.delay | SD-01 |
| GET/PUT /admin/business-rules | BusinessRuleRepo | – |
| GET /stores/{store_id}/twin (later extension) | DigitalTwinService | SD-13 |

Error body: `{"error": {"code": "CONFLICT|FORBIDDEN|NOT_FOUND|VALIDATION|UNAUTHORIZED|INTERNAL", "message": str, "details": []}}`
— 409 / 403 / 404 / 422 as listed, plus `UNAUTHORIZED` (401, missing or invalid token) and `INTERNAL`
(500, unhandled error, no internal details) (D-18). `details` items are `{"field": str|null, "message": str}`.

## 6. Cache (Redis)
Keys carry the run id: `{prefix}:{run_id}:{scope...}` with prefixes `dash`, `inbox`, `inv`, `twin`;
`latest_run_id` key points at the current successful run. TTL = seconds until next scheduled run.
Approvals/transfers call `invalidate_store_keys(store_ids, prefixes)`. Redis failure → log and read DB (fail-open).

## 7. Background jobs (Celery Beat)
| Task | Schedule | Diagram |
|---|---|---|
| nightly_run_task(run_date) | 23:30 IST daily; idempotent per run_date | SD-01 |
| approval_deadline_task() | every 15 minutes | SD-14 |
Agent order: SalesAnalytics → DemandForecasting → RelatedProduct → StockBalancing → Freshness → PurchaseOrder.
Critical agents (failure stops the run, no cache swap): DemandForecasting, StockBalancing, PurchaseOrder.

## 8. Function catalog
| Class / module | Function and parameters | Returns | Diagram |
|---|---|---|---|
| Celery task | nightly_run_task(run_date: date) | RunSummary | SD-01 |
| WorkflowOrchestrator | run_nightly(run_id: UUID, run_date: date) | RunSummary | SD-01 |
| WorkflowOrchestrator | _run_agent(agent: BaseAgent, ctx: RunContext) | AgentResult | SD-01 |
| BaseAgent (all 6) | run(ctx: RunContext) | AgentResult | SD-03 to SD-09 |
| DataIngestionService | load_and_validate(run_date: date, store_ids: list[UUID]) | ValidationReport | SD-02 |
| AgentRunLogger | start_run(agent_name: str, parent_run_id: UUID\|None, input_ref: dict) | UUID | SD-01 |
| AgentRunLogger | log_tool_call(run_id, tool_name, args, result_summary, duration_ms, status) | None | SD-02 to SD-09 |
| AgentRunLogger | log_evidence(run_id, rec_id, data: dict, validation_result: str) | None | SD-02, 03, 05, 06 |
| AgentRunLogger | log_llm_usage(run_id, provider, model, input_tokens, output_tokens) | None | SD-09 |
| AgentRunLogger | finish_run(run_id, status, output_summary, error) | None | SD-01 |
| LostSalesCalculator | estimate(daily_sales, stockout_days, margins: DataFrame) → lost_revenue, lost_profit | DataFrame | SD-03 |
| ForecastTools | classify_abc_xyz(series, value_col='revenue', a_cut=0.8, b_cut=0.95, x_cv=0.5, y_cv=1.0) | DataFrame | SD-04 |
| ForecastTools | baseline_avg_daily(df: DataFrame, window_days: int = 28) | DataFrame | SD-04 |
| ForecastTools | fit_statsforecast(df, models: list, horizon: int, n_windows: int = 3)  [ext] | DataFrame | SD-04 |
| ForecastTools | select_best(cv_results: DataFrame, baseline: DataFrame)  [ext] | DataFrame | SD-04 |
| ForecastTools | apply_calendar_uplift(forecast, events, uplift_by_type: dict)  [ext] | DataFrame | SD-04 |
| BasketTools | to_basket_matrix(lines: DataFrame) | DataFrame[bool] | SD-05 |
| BasketTools | mine_rules(basket, min_support=0.005, min_confidence=0.2, min_lift=1.0, max_len=2) | DataFrame | SD-05 |
| BasketTools | detect_substitutes(daily_sales, stockout_days, same_category_only=True, uplift_threshold=0.3) | DataFrame | SD-05 |
| BasketTools | find_assortment_gaps(rules_by_store: dict, listings: DataFrame, min_lift=1.5, min_stores=1) | list[GapSuggestion] | SD-05 |
| RequirementCalculator | own_requirement(daily_demand, lead_time_days, review_period_days, safety_stock_days, min_display_qty) | int | SD-06, SD-12 |
| RequirementCalculator | available(shelf_qty: int, backroom_qty: int, incoming: int, reserved: int) | int | SD-06, SD-12, SD-15 |
| RequirementCalculator | surplus(available: int, requirement: int) | int | SD-06, SD-12 |
| RequirementCalculator | assert_donor_protected(donor: StoreState, qty: int) | bool | SD-07 |
| TransferDecisionEngine | decide(product_id, states, routes, cost_inputs: CostInputs) | TransferPlan | SD-06, SD-07 |
| TransferDecisionEngine | find_expiry_receivers(product_id, qty, days_left, from_store, states, routes) | list[TransferProposal] | SD-08 |
| MarkdownRules | recommend(days_left: int, at_risk: int, unit_margin: Decimal, rules: list)  [ext] | MarkdownAction | SD-08 |
| POBuilder | select_supplier(need, offers, required_by: date, scores: dict\|None = None) | SupplierOffer\|None | SD-09 |
| POBuilder | consolidate(assigned: list[tuple[ReplenishmentNeed, SupplierOffer]]) | list[DraftPO] | SD-09 |
| POBuilder | round_to_pack(qty: int, order_pack_size: int, moq: int) | int | SD-09 |
| POBuilder | apply_scheme(line, schemes, daily_demand, shelf_life_days, budget_remaining)  [ext] | POLine | SD-09 |
| POBuilder | validate(po, rules: BusinessRules, budget_remaining: Decimal) | ValidationResult | SD-09, SD-10 |
| POBuilder | prioritise_within_budget(po: DraftPO, budget: Decimal) | DraftPO | SD-09 |
| POBuilder | apply_edits(po, edits: list[POLineEdit], store_id: UUID) | PurchaseOrder | SD-10 |
| ExplanationService | explain(items: list[ExplanationInput]) | list[str] | SD-09 |
| LLMClient | complete(system: str, prompt: str, max_tokens: int = 1000, temperature: float = 0) | LLMResponse | SD-09 |
| ApprovalService | decide(req: ApprovalRequest, user: User) | ApprovalResult | SD-10 |
| PurchaseOrderService | submit(po_id: UUID) | SubmissionResult | SD-10 |
| SupplierGateway | submit(po: PurchaseOrder) | SupplierAck | SD-10 |
| DashboardService | get_summary(store_id: UUID\|None, period: Period) | DashboardSummary | SD-11 |
| TransferService | accept(transfer_id: UUID, user: User) | TransferOrder | SD-12 |
| TransferService | approve_release(transfer_id: UUID, user: User) | TransferOrder | SD-12 |
| TransferService | dispatch(transfer_id: UUID, user: User) | TransferOrder | SD-12 |
| TransferService | receive(transfer_id: UUID, received_qty: int, user: User) | TransferOrder | SD-12 |
| DigitalTwinService | get_shelf_states(store_id: UUID)  [ext] | StoreTwinDTO | SD-13 |
| CacheService | get_latest_run_id() / set_latest_run_id(run_id) | UUID / None | SD-01, SD-11 |
| CacheService | key(prefix: str, run_id: UUID, *parts) | str | SD-11, SD-13 |
| CacheService | get(key: str) / set(key: str, value: str, ttl: int) | str\|None / bool | SD-11, SD-13 |
| CacheService | warm(run_id, store_ids) / invalidate_run(run_id) | int | SD-01 |
| CacheService | invalidate_store_keys(store_ids: list[UUID], prefixes: list[str]) | int | SD-10, SD-12 |
| MaterializedViewRefresher | refresh_dashboard_views() | None | SD-01 |
| RequirementCalculator | demand_window(lead_time_days: int, review_period_days: int) | int | SD-04, SD-06 |
| CostModel | transfer_incremental_cost(route: TransferRoute, qty: int) | Decimal | SD-07 |
| CostModel | po_incremental_cost(qty, unit_cost, donor, terms, order_fixed_share, delivery_charge_share, holding_rate, expiry_risk_pct, is_perishable, days_to_sell_cap) | Decimal | SD-07 |
| CostModel | days_to_sell(qty: int, daily_demand: float, cap_days: int) | Decimal | SD-07 |
| RequirementCalculator | co_replenish_qty(available: int, daily_demand: float, review_period_days: int, requirement: int) | int (0 = does not qualify) | SD-06 |
| RequirementCalculator | lead_time(terms_lead: int\|None, product_lead: int\|None, default_lead: int) | int | SD-04, SD-06 |
| RunSupersession | supersede_previous(run_id: UUID) | SupersedeSummary | SD-01 |
| DataIngestionService | backfill(start: date, end: date, store_ids: list[UUID]) | ValidationReport | SD-02 |
| GoodsReceiptService | receive(po_id: UUID, lines: list[ReceiptLine], user: User) | PurchaseOrder | SD-16 |
| PurchaseOrderService | resolve_needs_review(po_id: UUID, decision: ResolveRequest, user: User) | PurchaseOrder | – |
| PurchaseOrderService | close_short(po_id: UUID, reason: str, user: User) (Phase 6) | PurchaseOrder | – |
| RequirementCalculator | planning_incoming(incoming_items: list[IncomingItem], on_order_pending: int, run_date: date, grace_days: int) | int | SD-06 |
| TransferDecisionEngine | mark_po_pairs(states_by_product: dict, terms) (pass 1) | set[tuple[UUID, UUID]] | SD-06, SD-07 |
| TransferDecisionEngine | _priority(state: StoreState, lead_time_days: int) | "HIGH" \| "NORMAL" | SD-07 |
| FreshnessTools | at_risk_by_batch(batches: Sequence[BatchLike], daily_demand: float, run_date: date) (D-20) | list[BatchRisk] | SD-08 |
| BasketTools | detect_substitutes(…, min_stockout_days: int = 3) — extra parameter (D-22) | DataFrame | SD-05 |

Tool parameters typed as ORM models in this table (TransferRoute, SupplierStoreTerms, PurchaseOrder, POLine, Batch)
are read-only `Protocol`s in `app/tools/types.py`; `apply_edits` and `split` take and return `DraftPO` (D-19).
Defaults for ABC/XYZ, ADI, baseline, rule filtering, bill cleaning, expiry receivers, supplier choice and budget
trimming are recorded in decision D-22.
| NotificationService | notify(role: Role\|None, store_id: UUID\|None, message: str, link: str\|None) / list_for(user) / mark_read(id, user) | Notification / list / None | SD-14 |
| BasketTools | clean_bills(lines: DataFrame, rules: BasketQualityRules) | DataFrame | SD-05 |
| InventoryLedgerService | post(movements: list[InventoryMovement]) | None | SD-02, SD-12 |
| InventoryLedgerService | reconcile(store_id: UUID, snapshot: list[StockRow]) | list[InventoryMovement] | SD-02 |
| TransferService | reject(transfer_id: UUID, reason: str, user: User) | TransferOrder | SD-12 |
| ApprovalService | expire_overdue(now: datetime) | int | SD-14 |
| ApprovalService | _decide_escalated_lines(po, req, user) (Super Admin, L1 on behalf of store) | None | SD-10 |
| ApprovalService | _finalise_l1(po: PurchaseOrder) | PurchaseOrder | SD-10, SD-14 |
| POBuilder | split(po: PurchaseOrder, lines: list[POLine]) | PurchaseOrder (child) | SD-10, SD-14 |
| Celery task | approval_deadline_task() | int | SD-14 |
| StoreInventoryService | get_view(store_id: UUID, filters: InventoryFilter) | StoreInventoryDTO | SD-15 |
| TransferService | _apply_commitment(t: TransferOrder, event: str) (incoming / reserved per §2) | None | SD-12 |

## 9. Default parameters (BusinessRule / RunParams)
| Parameter | Default | Purpose |
|---|---|---|
| max_steps | 50 | Maximum tool steps per agent run (SD-01) |
| MAX_RETRIES | 2 | Retries for transient errors, with backoff (SD-01) |
| stale_days | 3 | Days without sales (while stock > 0) before a SKU is marked low-confidence (SD-02) |
| kpi_lookback_days | 28 | Window for KPIs and lost sales (SD-03) |
| lookback_days (forecast) | 180 | Sales history used for forecasting (SD-04) |
| window_days (baseline) | 28 | Moving-average window for baseline forecast (SD-04) |
| min_history_days | 56 | Minimum history before statsforecast models are tried (SD-04, extension) |
| horizon_days | 14 (minimum) | Minimum forecast horizon; actual horizon = longest lead + review + safety window in the run (SD-04) |
| ADI threshold | 1.32 | Average demand interval separating smooth vs intermittent SKUs (SD-04) |
| min_bills | 500 | Minimum bills per store before basket analysis (SD-05) |
| min_support / min_confidence / min_lift | 0.005 / 0.2 / 1.0 | Association rule thresholds (SD-05) |
| co-replenish min_lift / limit | 1.5 / 3 | Complements checked per reordered product (SD-06, D-02) |
| perishable_max_shelf_life_days | 30 | Products with shelf life ≤ this are perishable (expiry risk in SD-07, D-10) |
| days_to_sell_default_cap | 90 | Cap on days to sell donor surplus when the product has no shelf life (SD-07, D-10) |
| incoming_overdue_grace_days | 3 | Incoming past expected date + grace is flagged overdue and not counted in available (SD-06, D-16) |
| expiry_window_days | 14 | Batches scanned for expiry risk (SD-08) |
| po_l2_threshold | Business rule | PO value at or above which L2 approval is needed (SD-09, SD-10) |
| weekly_budget | Business rule | Spend cap used by budget validation (SD-09) |
| order_fixed_cost | Business rule | Fixed cost per PO used in transfer-vs-PO comparison (SD-07) |
| React Query staleTime | 300 000 ms | Client cache freshness for dashboard and twin (SD-11, SD-13) |
| Redis TTL | until next run | Cache keys expire at the next scheduled run; keys also carry run_id (SD-11) |
| holding_cost_rate_per_day | Business rule | Daily holding cost rate applied to donor surplus in the PO incremental cost (SD-07) |
| expiry_risk_pct | Business rule | Expected expiry loss share for perishable donor surplus (SD-07) |
| l1_deadline_hours | Business rule (e.g. 24) | Time allowed for store supervisors to decide their PO lines (SD-09, SD-14) |
| deadline_action | ESCALATE or EXPIRE | What happens to undecided lines at the deadline (SD-14) |
| basket.max_qty_per_line / exclude_promo_days | Business rule / true | Bulk-bill filter and promotion-day exclusion for basket mining (SD-05) |
| approval deadline job | every 15 minutes | Celery Beat schedule for SD-14 |

Placeholder defaults to confirm with the business: `holding_cost_rate_per_day = 0.0005` (≈18%/year),
`expiry_risk_pct = 0.10` (perishables), `l1_deadline_hours = 24`, `deadline_action = "ESCALATE"`,
`po_l2_threshold = 50000` (₹), `weekly_budget = 500000` (₹), `order_fixed_cost = 250` (₹),
`basket.max_qty_per_line = 24`, `basket.exclude_promo_days = true`.

## 10. Database notes
- Primary keys UUID (uuid7 or gen_random_uuid()) for entity tables; all FKs indexed; `created_at/updated_at`
  on every table.
- Composite primary keys (D-06): `store_product (store_id, product_id)`, `supplier_product (supplier_id, product_id)`,
  `supplier_store_terms (supplier_id, store_id)`, `inventory_position (store_id, product_id)`,
  `forecast (run_id, store_id, product_id)`, `kpi_snapshot (run_id, store_id, metric, product_key)` where
  `product_key` = product_id or the nil UUID for store-level KPIs, `lost_sales_estimate (run_id, store_id, product_id)`,
  `transfer_route (from_store_id, to_store_id)`, `inventory_daily_snapshot (store_id, product_id, snapshot_date)`.
- Partition `sales_line` by month on `txn_date` (PK `(bill_id, line_no, txn_date)`; a bill line is identified by
  `(bill_id, line_no)`) and `inventory_movement` by month on `created_at` (PK `(movement_id, created_at)`);
  index `(store_id, product_id, date)` on both.
- New columns (D-02, D-05, D-06, D-07, D-08): `store_product.preferred_supplier_id`;
  `sales_line.txn_date`, `sales_line.line_no`, `sales_line.store_id` (denormalised for partition-local queries);
  `replenishment_need.reason`, `.lift`, `.rec_id`; `transfer_order.expected_qty`, `.received_qty`, `.loss_value`;
  `po_line.received_qty`, `po_line.short_closed_qty` (D-16); status value `SUPERSEDED` on recommendation,
  transfer_order, purchase_order, po_line; `purchase_order.submitted_at` (expected date for overdue incoming, D-16).
- New tables: `inventory_daily_snapshot` (D-09), `goods_receipt` + `goods_receipt_line` (D-08),
  `notification` (D-08).
- Materialized views: `mv_dashboard_store_day`, `mv_inbox_counts`; refreshed CONCURRENTLY after each run (needs unique index).
- Row locks: `SELECT … FOR UPDATE` for PO approval and transfer transitions; `SKIP LOCKED` in the deadline job.
- Tables (CD-1, CD-2): store, product, store_product, supplier, supplier_product, supplier_store_terms,
  supplier_scheme(ext), calendar_event, sales_transaction, sales_line, inventory_position, inventory_movement,
  batch, inventory_daily_snapshot, forecast, association_rule, recommendation, replenishment_need, kpi_snapshot,
  lost_sales_estimate, app_user, purchase_order, po_line, goods_receipt, goods_receipt_line, transfer_order,
  transfer_route, approval, business_rule, notification, agent_run, tool_call, decision_evidence, llm_usage,
  store_layout(ext), shelf_location(ext).
