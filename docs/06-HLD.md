# RetailPilot AI — High-Level Design (HLD)

This document specifies the system-level architecture, data flows, deployment topology, security model, and non-functional requirements for the RetailPilot AI replenishment platform.

For detailed formulas, function signatures, and table schemas, refer to:
- **Business Requirements:** [`docs/01-business-requirements-v2.2.md`](01-business-requirements-v2.2.md)
- **Technical Specification:** [`docs/02-technical-spec.md`](02-technical-spec.md)
- **Design System:** [`docs/03-design-system.md`](03-design-system.md)
- **Decision Log:** [`docs/05-decision-log.md`](05-decision-log.md)
- **Diagrams:** [`docs/diagrams/`](diagrams/) (`cd1`–`cd4`, `sd01`–`sd16`, `erd.puml`)

---

## 1. System Overview & Architecture

RetailPilot AI is an automated, explainable replenishment and stock-balancing platform for multi-store FMCG supermarket chains. The platform:
1. Forecasts store-SKU daily demand and identifies cross-category basket affinities (co-replenishment).
2. Balances stock between company-owned stores before issuing supplier orders, comparing marginal incremental costs.
3. Consolidates supplier orders into store-grouped POs with human-in-the-loop approvals (line-level L1 supervisor review, automated escalation, and L2 value-threshold approval).
4. Tracks every inventory change through an immutable double-entry stock movement ledger.
5. Employs LLM-powered explanation generation grounded strictly in deterministic mathematical evidence.

### 1.1 Container Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        User Web Browser                                │
│          React 19 + TypeScript (Vite, TanStack Query/Table, Tailwind)  │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ HTTPS / REST (JSON)
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend API                               │
│       - Auth & Role Scoping (JWT / bcrypt)                             │
│       - Thin Routers -> Service Layer -> Domain Repositories           │
│       - Async Engine (psycopg 3 async pool, 5s timeout)                │
└───────────────────────┬─────────────────────────┬──────────────────────┘
                        │                         │
                        ▼                         ▼
┌───────────────────────────────┐ ┌──────────────────────────────────────┐
│       Redis 7 Cache           │ │         PostgreSQL 16 DB             │
│ - Dashboard / Inbox Cache     │ │ - Master Data & Planning Outputs     │
│ - Fail-open fallback to DB    │ │ - Monthly Partitioned Tables:        │
│ - Celery Task Broker          │ │     sales_line, inventory_movement   │
└───────────────▲───────────────┘ │ - Materialized Views:                │
                │                 │     mv_dashboard_store_day           │
                │                 │     mv_inbox_counts                  │
┌───────────────┴───────────────┐ └──────────────────▲───────────────────┘
│   Celery Workers & Beat       │                    │
│ - Nightly Orchestrator Run    │ ───────────────────┘
│ - 6 Replenishment Agents      │ Sync Engine (statement_timeout 10 min)
│ - Approval Deadline Watcher   │
│ - Future Partition Creator    │
│ - Anthropic Claude LLM        │
└───────────────────────────────┘
```

---

## 2. Core Data Flows

### 2.1 Ingestion & Ledger Posting Flow ([`sd02_ingestion.puml`](diagrams/sd02_ingestion.puml))
- POS bills and goods receipts are loaded into unlogged staging tables using PostgreSQL `COPY`.
- Staging data is validated, mapped to business dates, and ingested into partitioned tables (`sales_transaction`, `sales_line`).
- Stock balance mutations execute strictly through `InventoryLedgerService.post()`, writing an immutable `inventory_movement` row and adjusting `inventory_position` (`shelf_qty`, `backroom_qty`, `incoming`, `reserved`).

### 2.2 Nightly Replenishment Pipeline ([`sd01_orchestration.puml`](diagrams/sd01_orchestration.puml))
Orchestrated by `WorkflowOrchestrator.run_nightly()` through Celery Beat:
1. **Sales Analytics Agent ([`sd03`](diagrams/sd03_sales_analytics.puml)):** Updates ABC/XYZ velocity classifications and detects revenue-impacting stockout days.
2. **Forecasting Agent ([`sd04`](diagrams/sd04_forecasting.puml)):** Computes 7-day and 14-day baseline demand, festival multiplier spikes, and flags forecast confidence.
3. **Related Products Agent ([`sd05`](diagrams/sd05_related_products.puml)):** Discovers market-basket association rules (lift, support, confidence) for co-replenishment.
4. **Stock Balancing Agent ([`sd06`](diagrams/sd06_stock_balancing.puml), [`sd07`](diagrams/sd07_transfer_decide.puml)):** Calculates store `own_requirement` and surplus. Decides peer-to-peer transfers versus supplier POs by comparing transport/handling costs against order fixed/delivery shares.
5. **Freshness & Expiry Agent ([`sd08`](diagrams/sd08_freshness.puml)):** Detects FEFO batch expiry risks; prioritises moving perishable batches to high-velocity sibling stores.
6. **Purchase Order Agent ([`sd09`](diagrams/sd09_purchase_order_agent.puml)):** Consolidates remaining shortfall and co-replenishment needs into supplier POs grouped by store.
7. **Explanation Service:** Calls Anthropic Claude (`LLM_MODEL`) using structured evidence. Validates generated text against deterministic numbers with fallback to templates.
8. **Cache Swap:** Refreshes materialized views concurrently and switches Redis cache keys to the new run version.

### 2.3 PO Approval & Split Flow ([`sd10`](diagrams/sd10_po_approval.puml), [`sd14`](diagrams/sd14_approval_deadline.puml))
- Store Supervisors review their store's line items on consolidated POs before the `l1_deadline`.
- Undecided lines automatically escalate to Super Admin.
- Approved lines split into a child PO (`SPLIT_PARTIAL`) for immediate supplier submission.
- POs exceeding the monetary threshold trigger L2 Super Admin review.

### 2.4 Peer Transfer Lifecycle ([`sd12`](diagrams/sd12_transfer_execution.puml))
- Destination supervisor accepts -> donor supervisor approves release -> surplus is re-checked against real-time stock -> dispatch -> receiving supervisor confirms count -> ledger writes `TRANSFER_IN` and records discrepancies.

---

## 3. Deployment & Infrastructure

### 3.1 Local Development Topology
- **Containers:** Managed via `infra/docker-compose.yml`:
  - `postgres:16`: Persistent volume, exposed on port 5432, healthcheck via `pg_isready`.
  - `redis:7`: Persistent append-only file, exposed on port 6379, healthcheck via `redis-cli ping`.
- **Backend API:** FastAPI running under Uvicorn with `psycopg` async connection pool.
  - Windows requires the `Selector` event loop (`--loop app.core.db:selector_event_loop`, D-36).
- **Background Worker:** Celery with Redis broker and result backend.
  - Windows local development: Run with `--pool=solo`.
  - Linux / Production container: Run with default multi-process prefork pool.
- **Frontend App:** Vite dev server hosting React 19 SPA, communicating with FastAPI via OpenAPI-generated client.

---

## 4. Security & Store Scoping

### 4.1 Authentication & Authorization
- **Token Mechanism:** Stateless JWT (`pyjwt`) signed with HMAC-SHA256, containing `sub` (user_id), `role`, and `store_id`. Passwords hashed with `bcrypt`.
- **Roles:**
  - `SUPER_ADMIN`: Full visibility across all stores, settings, system observability, L2 approvals, and escalated lines.
  - `STORE_SUPERVISOR`: Scoped strictly to their assigned `store_id`.

### 4.2 Multi-Tenant Store Data Isolation
- Supervisor queries are scoped at the repository level with `WHERE store_id = :user_store_id`.
- In cross-store recommendations and transfers, peer donor details are obfuscated to show only the sibling store's name and offered quantity.
- PO review endpoints enforce line-level store ownership: supervisors may only decide lines belonging to their store.

---

## 5. Non-Functional & Performance Architecture

### 5.1 Performance Targets
- **Read Latencies:**
  - Cached dashboard and inbox queries: **p95 < 200 ms** (via Redis cache).
  - Uncached database queries: **p95 < 500 ms**.
- **Materialized Views:** `mv_dashboard_store_day` and `mv_inbox_counts` provide pre-aggregated figures, refreshed concurrently upon nightly pipeline completion.

### 5.2 Resilience & Fail-Open Caching ([`sd11`](diagrams/sd11_dashboard_cache.puml))
- If Redis is unavailable, the API fails open by falling back directly to PostgreSQL queries without raising user-facing 500 errors.
- External LLM degradation falls back gracefully to deterministic rule-based explanation templates.

### 5.3 Database Concurrency & Integrity
- Monthly partitioning for high-volume append tables (`sales_line`, `inventory_movement`) with indexes inherited automatically by partitions.
- Scheduled Celery Beat maintenance job creates next-month partitions proactively and raises an alert if rows land in the `DEFAULT` partition.
- Optimistic/Pessimistic row locking (`SELECT ... FOR UPDATE`) guards against race conditions in PO line approvals, transfer dispatches, and inventory movements.

