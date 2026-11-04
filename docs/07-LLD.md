# RetailPilot AI — Low-Level Design (LLD)

This document details the module design, database ERD, state machines, API contracts, caching strategy, and error handling mechanics for the RetailPilot AI platform.

---

## 1. Entity-Relationship Model (ERD)

The complete entity-relationship model is generated directly from the SQLAlchemy domain models by `scripts/export_erd.py`. Its PlantUML source is located at:
- **ERD PlantUML:** [`docs/diagrams/erd.puml`](diagrams/erd.puml)
- **Domain Class Diagrams:** [`docs/diagrams/cd1_domain_core.puml`](diagrams/cd1_domain_core.puml), [`docs/diagrams/cd2_domain_workflow.puml`](diagrams/cd2_domain_workflow.puml)

### 1.1 Model Domain Grouping
The tables in `app/domain/models/` are partitioned into 9 domain boundaries:
1. **Master Data:** `store`, `product`, `store_product`, `supplier`, `supplier_product`, `supplier_store_terms`, `calendar_event`.
2. **Sales Transactions:** `sales_transaction`, `sales_line` (monthly range partitioned).
3. **Inventory & Stock Ledger:** `inventory_position` (current balances), `inventory_movement` (monthly range partitioned ledger), `batch` (FEFO expiry tracking), `inventory_daily_snapshot`.
4. **Planning Outputs:** `forecast`, `association_rule`, `replenishment_need`, `recommendation`, `lost_sales_estimate`, `kpi_snapshot`.
5. **Purchasing & Goods Receipt:** `purchase_order`, `po_line`, `goods_receipt`, `goods_receipt_line`.
6. **Transfers & Approvals:** `transfer_order`, `transfer_route`, `approval`, `business_rule`.
7. **Users & Notifications:** `app_user`, `notification`.
8. **Observability & Traceability:** `agent_run`, `tool_call`, `decision_evidence`, `llm_usage`.
9. **Extensions:** `store_layout`, `shelf_location`, `supplier_scheme`.

---

## 2. Module & Class Architecture

The backend repository follows a clean, layered architecture:

```
backend/app/
├── api/
│   └── routers/            # Thin FastAPI routers (auth, validation, status codes)
├── services/               # Transactional business workflows & orchestration
│   ├── approval_service.py # L1/L2 approval logic, deadlines, PO line splitting
│   ├── transfer_service.py # Peer transfer lifecycle & stock re-verification
│   ├── ledger_service.py   # Immutable inventory movements & reconciliations
│   ├── ingestion_service.py# Staging loads & validation via PostgreSQL COPY
│   └── dashboard_service.py# Dashboard KPIs & Redis cache-aside reads
├── tools/                  # 100% deterministic, side-effect free mathematical tools
│   ├── requirement.py      # RequirementCalculator (demand windows, own requirement)
│   ├── cost_model.py       # CostModel (incremental transport, handling, holding costs)
│   ├── transfer_engine.py  # TransferDecisionEngine (two-pass surplus balancing)
│   ├── po_builder.py       # POBuilder (MOQ rounding, pack sizes, line splitting)
│   ├── forecast.py         # ForecastTools (baseline demand, ABC/XYZ categorization)
│   └── basket.py           # BasketMiner (Apriori association rules, lift, confidence)
├── domain/
│   ├── models/             # Typed SQLAlchemy 2.0 ORM models
│   ├── schemas/            # Pydantic v2 DTOs (request/response schemas)
│   └── repositories/       # Database query encapsulation (SQLAlchemy select)
├── core/
│   ├── config.py           # Pydantic settings loaded from environment
│   ├── db.py               # Async API pool (5s timeout) + Sync Worker pool (10m timeout)
│   ├── errors.py           # AppError hierarchy with structured JSON serialization
│   └── security.py         # JWT generation/decoding and bcrypt password hashing
└── workers/
    ├── celery_app.py       # Celery instance & beat schedule
    └── tasks.py            # Nightly run, approval timeout, and partition tasks
```

---

## 3. Workflow State Machines

### 3.1 Transfer Order Lifecycle ([`sd12`](diagrams/sd12_transfer_execution.puml))

```
                    ┌──────────────┐
                    │   PROPOSED   │
                    └──────┬───────┘
                           │ Destination supervisor accepts
                           ▼
                    ┌──────────────┐
                    │ DEST_ACCEPTED│ ──── (Donor declines) ───► REJECTED
                    └──────┬───────┘
                           │ Donor supervisor approves release
                           ▼
                 ┌──────────────────┐
                 │ APPROVED_RELEASE │
                 └─────────┬────────┘
                           │ Dispatch confirmed (surplus re-verified)
                           ▼
                    ┌──────────────┐
                    │  DISPATCHED  │
                    └──────┬───────┘
                           │ Receiving supervisor confirms qty
                           ▼
                    ┌──────────────┐
                    │   RECEIVED   │
                    └──────────────┘
```
- **Commitments:** On `DEST_ACCEPTED`, receiver `incoming += qty` and donor `reserved += qty`. If rejected or superseded, commitments are released.
- **Superseded:** Untouched proposed transfers become `SUPERSEDED` when replaced by the next nightly run.

### 3.2 Purchase Order & Line Lifecycle ([`sd10`](diagrams/sd10_po_approval.puml), [`sd14`](diagrams/sd14_approval_deadline.puml))

```
            ┌──────────────┐
            │  PENDING_L1  │ ──── (All lines approved & ≤ L2 threshold) ────► APPROVED
            └──────┬───────┘
                   │ Some lines approved, others escalated/rejected
                   ▼
         ┌───────────────────┐
         │   SPLIT_PARTIAL   │ ──► Child PO created for approved lines (APPROVED)
         └───────────────────┘
                   │
                   │ Value > L2 threshold (or escalated lines approved)
                   ▼
            ┌──────────────┐
            │  PENDING_L2  │ ──── (Super Admin approves) ───────────────────► APPROVED
            └──────┬───────┘
                   │ Super Admin rejects
                   ▼
            ┌──────────────┐
            │   REJECTED   │
            └──────────────┘
```
- **Line-Level L1:** Each line is `PENDING`. Store supervisors approve/reject lines for their store.
- **Deadline Escalation:** If lines remain undecided at `l1_deadline`, lines transition to `ESCALATED` for Super Admin decision.

---

## 4. API Contract & Cursor Pagination

### 4.1 Endpoint Summary (Spec §5)

| Endpoint | Method | Role | Description |
|---|---|---|---|
| `/api/v1/auth/login` | POST | Public | Authenticates credentials, returns signed JWT |
| `/api/v1/auth/me` | GET | Authenticated | Returns current user profile, role, and store |
| `/api/v1/dashboard/summary` | GET | Authenticated | Store KPIs (revenue, stockouts, cover, health) |
| `/api/v1/inventory` | GET | Authenticated | Store inventory positions (shelf, backroom, available) |
| `/api/v1/inventory/movements` | GET | Authenticated | Stock ledger movements (**cursor-paged**, D-37) |
| `/api/v1/recommendations` | GET | Authenticated | Inbox list of replenishment & transfer proposals |
| `/api/v1/recommendations/{id}` | GET | Authenticated | Detailed recommendation with evidence & LLM text |
| `/api/v1/purchase-orders` | GET | Authenticated | List consolidated purchase orders |
| `/api/v1/approvals` | POST | Authenticated | Submit L1 or L2 approval/rejection decisions |
| `/api/v1/transfers/{id}/accept` | POST | Supervisor | Destination store supervisor accepts transfer |
| `/api/v1/transfers/{id}/dispatch`| POST | Supervisor | Donor store supervisor dispatches goods |
| `/api/v1/transfers/{id}/receive` | POST | Supervisor | Destination store confirms receipt |

### 4.2 Cursor Pagination for Movements (`D-37`)
Movement queries use opaque base64-encoded cursors over `(occurred_at, movement_id)`:
- Guarantees zero page-drift when new movements are written concurrently.
- No `COUNT(*)` overhead on large partitioned ledger tables.

---

## 5. Cache Strategy & Error Handling

### 5.1 Run-Versioned Redis Caching ([`sd11`](diagrams/sd11_dashboard_cache.puml))
- **Cache Key Template:** `dash:{run_version}:{store_id}` and `inbox:{run_version}:{store_id}`.
- **Atomic Cache Swap:** Upon nightly pipeline completion, `run_version` is updated in Redis, immediately activating fresh cache keys without flushing.
- **Fail-Open Strategy:** If Redis fails or times out, the service catches the exception and queries PostgreSQL directly.

### 5.2 Structured Error Handling (`app/core/errors.py`)
All error responses return standard JSON:
```json
{
  "code": "STOCK_INSUFFICIENT",
  "detail": "Donor store 101 has insufficient surplus (available 12, requested 20)",
  "status_code": 409,
  "field_errors": null
}
```
Standard status codes:
- **401 Unauthorized:** Missing or expired JWT.
- **403 Forbidden:** Store supervisor attempting cross-store action or Super Admin endpoint.
- **404 Not Found:** Resource not found.
- **409 Conflict:** State transition conflict (e.g. transfer already dispatched, PO already finalised).
- **422 Unprocessable Entity:** Schema validation failure or negative quantities.

