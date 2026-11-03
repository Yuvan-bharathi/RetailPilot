# RetailPilot AI — Technical Specification (implementation reference)

Derived from business requirements v2.2 and diagrams v3 (`docs/diagrams/`). Use these names, formulas and
states exactly. Values marked **(confirm)** are placeholder defaults stored in `BusinessRule` — never hard-code them.

## 1. Core formulas

```
demand_window_days   = lead_time_days(store's supplier) + review_period_days
own_requirement      = ceil(daily_demand × demand_window_days)
                       + ceil(daily_demand × safety_stock_days)
                       + min_display_qty
on_hand              = shelf_qty + backroom_qty
available            = shelf_qty + backroom_qty + incoming − reserved
surplus              = available − own_requirement          (≤ 0 → not a donor)
need (short store)   = own_requirement − available          (> 0 → short)
days_of_cover        = available / max(daily_demand, 0.01)

transfer_incremental_cost = fixed_cost + per_unit_cost × qty + handling_cost_per_unit × qty
po_incremental_cost       = order_fixed_share + delivery_charge_share
                          + qty × unit_cost × holding_cost_rate_per_day × days_to_sell_at_donor
                          + qty × unit_cost × expiry_risk_pct            (perishables only)
   where days_to_sell_at_donor = qty / donor.daily_demand ; purchase price itself is NOT included
transfer chosen if  transfer_incremental_cost < po_incremental_cost
                AND route.transit_days ≤ lead_time_days of the short store's supplier
                AND donor stays ≥ own_requirement after the transfer (donor protection)

lost_units   = demand rate on in-stock days × stockout_days
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

**POLine.line_status**: `PENDING → APPROVED | EDITED | REJECTED | ESCALATED | EXPIRED`.
L1 is finalised when no line is PENDING (or at deadline, SD-14). Approved/edited lines continue; if any line is
rejected/expired, approved lines move to a child PO (`parent_po_id`). L2 threshold uses the continuing PO's value.

**TransferOrder.status**: `PROPOSED → DEST_ACCEPTED → DONOR_APPROVED → DISPATCHED → RECEIVED`;
`PROPOSED → REJECTED` (destination declines); `DEST_ACCEPTED → CANCELLED` (surplus gone at re-check;
need carried forward to next PO run).

**Recommendation.status**: `PENDING → ACCEPTED | EDITED | REJECTED | NEEDS_REVIEW`.
**AgentRun.status**: `RUNNING → SUCCESS | PARTIAL | FAILED`.

## 3. Inventory movement ledger
All stock changes are `InventoryMovement` rows; `InventoryPosition` is a maintained projection.

| movement_type | qty sign | location | created by |
|---|---|---|---|
| SALE | − | SHELF | ingestion (SD-02) |
| PO_RECEIPT | + | BACKROOM | goods receipt |
| TRANSFER_OUT | − | BACKROOM | dispatch (SD-12) |
| TRANSFER_IN | + | BACKROOM | receipt (SD-12) |
| SHELF_REFILL | −backroom / +shelf (pair) | both | store task |
| ADJUSTMENT | ± | either | reconciliation vs POS snapshot (SD-02) |
| EXPIRY_WRITE_OFF | − | either | freshness / store action |

Transit loss (received < sent) is recorded as a discrepancy on the transfer (no extra movement — both sides are already correct).

## 4. Roles and permissions

| Capability | Store Supervisor | Super Admin |
|---|---|---|
| Data scope | own store only | all stores |
| PO lines L1 (own store) | ✓ | ✓ for escalated lines |
| PO L2 | – | ✓ |
| Transfer: accept incoming / approve release / dispatch / receive | ✓ for own store's side | view |
| Business rules, suppliers, stores, users | – | ✓ |
| Agent runs / system monitoring | – | ✓ |
Cross-store rule: a supervisor sees another store only as name + offered/requested quantity.

## 5. API (FastAPI, prefix /api/v1, JWT bearer; all list endpoints paginated)

| Method & path | Handler → service | Diagram |
|---|---|---|
| POST /auth/login | issue JWT (seeded PoC users) | – |
| GET /dashboard?store_id&period | DashboardService.get_summary | SD-11 |
| GET /stores/{store_id}/inventory?category&status&aisle | StoreInventoryService.get_view | SD-15 |
| GET /recommendations?store_id&status&type | RecommendationService.list_inbox | – |
| GET /recommendations/{rec_id} | RecommendationService.get_detail (evidence) | – |
| GET /purchase-orders?status&store_id · GET /purchase-orders/{po_id} | PO queries | – |
| POST /approvals | ApprovalService.decide | SD-10 |
| POST /transfers/{id}/accept · /approve-release · /reject · /dispatch · /receive | TransferService | SD-12 |
| GET /agent-runs · GET /agent-runs/{run_id} | ObservabilityService | – |
| POST /admin/runs (trigger nightly run manually, Super Admin) | nightly_run_task.delay | SD-01 |
| GET/PUT /admin/business-rules | BusinessRuleRepo | – |
| GET /stores/{store_id}/twin (later extension) | DigitalTwinService | SD-13 |

Error body: `{"error": {"code": "CONFLICT|FORBIDDEN|NOT_FOUND|VALIDATION", "message": str, "details": []}}`.

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
| CostModel | po_incremental_cost(qty, unit_cost, donor, terms, order_fixed_share, holding_rate, expiry_risk_pct) | Decimal | SD-07 |
| BasketTools | clean_bills(lines: DataFrame, rules: BasketQualityRules) | DataFrame | SD-05 |
| InventoryLedgerService | post(movements: list[InventoryMovement]) | None | SD-02, SD-12 |
| InventoryLedgerService | reconcile(store_id: UUID, snapshot: list[StockRow]) | list[InventoryMovement] | SD-02 |
| TransferService | reject(transfer_id: UUID, reason: str, user: User) | TransferOrder | SD-12 |
| ApprovalService | expire_overdue(now: datetime) | int | SD-14 |
| ApprovalService | _finalise_l1(po: PurchaseOrder) | PurchaseOrder | SD-10, SD-14 |
| POBuilder | split(po: PurchaseOrder, lines: list[POLine]) | PurchaseOrder (child) | SD-10, SD-14 |
| Celery task | approval_deadline_task() | int | SD-14 |
| StoreInventoryService | get_view(store_id: UUID, filters: InventoryFilter) | StoreInventoryDTO | SD-15 |

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
| co-replenish min_lift / limit | 1.5 / 3 | Complements checked per reordered product (SD-06) |
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
- Primary keys UUID (uuid7 or gen_random_uuid()); all FKs indexed; `created_at/updated_at` on every table.
- Partition `sales_line` and `inventory_movement` by month on date; index `(store_id, product_id, date)`.
- Materialized views: `mv_dashboard_store_day`, `mv_inbox_counts`; refreshed CONCURRENTLY after each run (needs unique index).
- Row locks: `SELECT … FOR UPDATE` for PO approval and transfer transitions; `SKIP LOCKED` in the deadline job.
- Tables (CD-1, CD-2): store, product, store_product, supplier, supplier_product, supplier_store_terms,
  supplier_scheme(ext), calendar_event, sales_transaction, sales_line, inventory_position, inventory_movement,
  batch, forecast, association_rule, recommendation, replenishment_need, kpi_snapshot, lost_sales_estimate,
  app_user, purchase_order, po_line, transfer_order, transfer_route, approval, business_rule,
  agent_run, tool_call, decision_evidence, llm_usage, store_layout(ext), shelf_location(ext).
