# RetailPilot AI — demo script

Everything shown comes from the synthetic dataset (`data/synthetic`, fixed seed) run through the real nightly
pipeline — no hand-written recommendations. Expected numbers are the planted values of
[04-demo-scenarios.md](04-demo-scenarios.md) and are asserted by `backend/tests/scenarios/test_demo_scenarios.py`.

## 1. Set up (about 1–2 minutes)

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d     # repo root
cd backend
uv run alembic upgrade head
uv run python -m scripts.reset_demo        # empty business data (keeps business rules)
uv run python -m scripts.seed_demo         # generate + load the small dataset, create users, run the nightly pipeline
uv run uvicorn app.main:app --reload --loop app.core.db:selector_event_loop
cd ../frontend && npm run dev              # .env.development: real API (VITE_USE_MOCKS=false)
```

Explanations use Groq (`GROQ_API_KEY`, D-44); without a key the deterministic templates are used and the numbers
are identical. `seed_demo --profile full` loads 180 days × 500 bills/day for performance runs; in that profile the
bread→butter pair of scenario 4 falls below `basket.min_support`, so the demo uses the small profile (D-47).

| Login | Password | Role | Store |
|---|---|---|---|
| `admin` | `demo` | Super Admin | all stores |
| `sup.a` | `demo` | Store Supervisor | Store A - Residential |
| `sup.b` | `demo` | Store Supervisor | Store B - College area |
| `sup.c` | `demo` | Store Supervisor | Store C - Temple street |

The nightly run is for **3 Nov 2026** (history ends 2 Nov). The header shows "Data as of 2 Nov 2026".

## 2. The five scenarios

### Scenario 1 — sells high everywhere → purchase orders only (Rice 5 kg)
- **Login** `admin` → Recommendations, filter *Reorder*, search "Rice".
- **Expect** reorders of **35** (Store A), **45** (Store B), **51** (Store C); reason *No other store has stock to
  spare* (`NO_SURPLUS_IN_ANY_STORE`); **no transfer** — no store has surplus (rule 2).
- **Open** one: the evidence shows daily demand, lead time of that store's supplier, review period, own requirement
  and available.

### Scenario 2 — surplus covers the need → transfer only (Tea 250 g)
- **Login** `sup.c` → Recommendations → *Transfer · Tea 250 g*: **20** units from **Store A**.
- The destination supervisor sees Store A only as **name + quantity** and "Donor keeps its full requirement" — no
  donor stock figures (rule 10). No purchase order for tea in Store C.

### Scenario 3 — partial surplus → transfer + purchase order (Biscuits 200 g)
- **Login** `sup.c`: *Transfer 24* from Store A **and** *Reorder 16*; the detail shows both quantities separately
  and the incremental transfer cost vs the incremental PO cost (rules 4–5).
- **Login** `sup.a` (the donor) and open the same transfer: Store A's own surplus (**24**) and protected
  requirement are visible to the donor. `sup.b` gets "belongs to another store" (403).

### Scenario 4 — reorder with a co-replenished complement (Bread + Butter, Store A)
- **Login** `sup.a`: *Reorder 38* bread and *Co-replenish 3* butter — the butter evidence shows the basket rule
  (lift), and that butter would fall below its requirement before the next review while its supplier is already
  delivering to Store A (D-02, D-13).

### Scenario 5 — expiry risk → expiry-aware transfer (Paneer 200 g)
- **Login** `sup.c`: *Transfer 30* paneer from Store A, marked expiry-aware; the evidence shows the batch, days left
  and the 30 units Store A cannot sell before expiry (FEFO, D-31). Store A's Inventory → *Expiring soon* tab lists
  the batch.

## 3. Around the scenarios
- **Dashboard** (`admin`, then `sup.a`): KPIs, sales trend, stock health, expiry risk, POs by status — every figure
  from the API (D-46).
- **Approvals** (`sup.a`): decide Store A's lines of the consolidated purchase orders before the L1 deadline; the
  Super Admin decides escalated lines and L2.
- **Transfers**: accept (destination) → approve release (donor) → dispatch → receive; the ledger moves stock.
- **Monitoring** (`admin`): the run, its six agents, tool calls and LLM usage; *Trigger nightly pipeline* runs the
  next day.

## 4. Automated walkthrough
`cd frontend && npm run e2e` drives Chromium through scenarios 1–5 and the dashboards as `admin`, `sup.a`, `sup.b`
and `sup.c` against the real API (Playwright; needs the demo loaded).

## 5. Edge cases planted in the data
- **Stock mismatch** (Store B, 23 Oct): the import posts a reconciliation ADJUSTMENT of −3 (rule 8).
- **Stale SKU** (Store C): no sales for 5 days while stock is held → LOW confidence, never transferred (D-04).
