# Gap analysis against requirements §9 (PoC scope)

Status of `docs/01-business-requirements-v2.2.md` §9 as of 4 Nov 2026 (commit after D-49). "Done" means implemented
**and** covered by an automated test; the evidence column names it. Decisions are in `docs/05-decision-log.md`.

## 9.1 Initial PoC

| Requirement | Status | Evidence |
|---|---|---|
| Multi-store executive dashboard | Done | `/dashboard`, `/dashboard/insights` (D-46); integration + UI + E2E tests |
| Store-level sales and product analysis | Done | `/analytics` categories, movers (D-48); scenario API test |
| Fast / slow movers | Done | dashboard movers (sale lines only) |
| Inventory and stock-out risk | Done | rule 1 requirement, D-46 risk bands; inventory integration test |
| Location-specific recommendations | Done | inbox scoped per store; per-viewer evidence (D-32) — API + E2E tests |
| Recommendations with evidence | Done | D-34 evidence on every recommendation (scenario test) |
| Draft PO creation and approval | Done | PO agent, line-level L1 / L2 (SD-10) — scenario + integration tests |
| Agent monitoring pages | Done | Monitoring page; `/agent-runs` Super Admin only |
| Logs, error states, metrics | Done | agent_run / tool_call / llm_usage; standard error body |
| Workflow and edge-case testing | Done | 5 scenarios through the real pipeline (13 tests) and in the browser (6 Playwright tests) |

## 9.2 Enhancements in the PoC

| Enhancement | Status | Evidence / note |
|---|---|---|
| Transfer vs PO on incremental cost, donor protection | Done | tools (100% coverage), scenarios 2–3 |
| Co-replenishment (basket rules, same store, D-02/D-13) | Done | scenario 4 (small profile — see D-47 for the full profile) |
| Lost revenue and lost profit, separately | Done | rule 9; Analytics top lost sales |
| Consolidated POs across stores | Done | PO agent; scenario test |
| ABC-XYZ classification | Done | forecasting agent; Analytics matrix |
| FEFO expiry risk and expiry-aware transfers | Done | scenario 5 |
| 2D store inventory view | Done | Inventory page (shelf / backroom / ledger / batches) |
| Shelf vs backroom and stock ledger | Done | ledger sums to positions (scenario test, rule 8) |
| Two-sided transfers, line-level PO approval | Done | SD-12 / SD-10 services and tests |

## 9.3 Extensions (time permitting)

| Extension | Status | Note |
|---|---|---|
| Pattern-specific forecasting | Partly | ETS / Croston-SBA / TSB with backtest selection exist but are **off** (no gain on the synthetic data, D-45); no calendar uplift |
| Scheme-aware ordering | Not done | `supplier_scheme` table only |
| Cash-aware ordering | Done | weekly budget with reduce-before-skip (D-29) |
| Rule-based markdowns | Not done | expiry alerts only; `markdown_enabled` is off |
| 3D digital twin | Not done | deferred by the requirements |

## Known limits
- Synthetic data only; evaluation figures (docs/EVALUATION_REPORT.md) measure fit to the generator's patterns.
- Nightly run on the full profile: ≈ 25 s of agents plus ≈ 4–5 min of Groq explanations under rate limits (D-47).
- Business rules are global; per-store overrides exist in the schema but nothing reads them yet (D-48).
- Pending owner confirmation: D-34 implementation choices, D-43 schema details.
