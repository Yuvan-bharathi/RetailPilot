# Sales Analytics

Key: `sales_analytics` · Group: PIPELINE · Kind: Deterministic · Pattern: PIPELINE_STAGE · Critical: no · Prompt version: none

## Purpose
Computes store revenue KPIs and estimates lost sales on stockout days. Lost revenue and lost profit are stored as
separate figures (rule 9). Implementation: `SalesAnalyticsAgent` in `backend/app/agents/sales_analytics.py`.

What the code writes today:
- one `kpi_snapshot` row per store with metric `revenue_28d` (window = `kpi_lookback_days`);
- `lost_sales_estimate` rows (`lost_units`, `lost_revenue`, `lost_profit`, `confidence`) from `LostSalesCalculator`
  (`app/tools/lost_sales.py`), only when there are both sales and stockout days (`closing_on_hand == 0`).

Note: the registry purpose mentions ABC-XYZ classes. In the code, ABC/XYZ classification is done by Demand
Forecasting (`ForecastTools.classify_abc_xyz`), not by this agent.

## 4D notes
- **Delegation** — Not an LLM: every figure is a calculation. Sales lines exclude voided lines, returns and qty ≤ 0.
- **Description** — SD-03, spec §8. Input is the lookback window of sales lines and daily snapshots.
- **Discernment** — Unit tests of the lost-sales tool; KPI totals reconcile with the sales ledger (registry).
- **Diligence** — Logged through `AgentRunLogger` as a child run of the nightly run. No approval: outputs are informational.

## System instructions
No LLM decisions and no explanation text.

## Input contract
`RunContext` (`run_id`, `run_date`, `store_ids`, `RunParams`). Business rule used: `kpi_lookback_days`.

## Output contract
`kpi_snapshot` rows and `lost_sales_estimate` rows keyed by `run_id`. `AgentResult.outputs`:
`kpis`, `lost_sales_rows`, `total_revenue`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `compute_kpis` (registry label; in-agent pandas sums) | read | revenue per store over the lookback |
| `estimate_lost_sales` (`LostSalesCalculator.estimate`) | read | lost units, revenue, profit, confidence per store-SKU |

These are deterministic functions, not LLM tools. Nothing here approves, submits, dispatches, receives, changes
rules or changes stock.

## State and memory
Within a run: none beyond in-memory data frames. Across runs: none; it only writes rows for its own `run_id`.

## Stopping conditions
`RunParams.max_steps` per stage; 2 attempts, then FAILED (`WorkflowOrchestrator.run_stage`).

## Failure handling
| Failure | Outcome |
|---|---|
| Exception in the agent | Retried once (2 attempts); then the stage is FAILED and the run becomes PARTIAL (non-critical) |
| No sales or no stockout days | No lost-sales rows; KPI rows written with revenue 0 where a store has no sales |
| Run Coordinator on | May choose `RETRY_AGENT` once for this non-critical stage |

## Human-in-the-loop
None — informational KPIs.

## When turned off
KPIs and lost revenue/profit are not refreshed; screens show "as of <last run>". Stock Balancing is told it runs
without this input (`input_missing` WARN log) and reorder evidence has no lost revenue/profit. This stage still runs
while replenishment is PAUSED (`_RUN_WHILE_PAUSED`).

## Evaluation
- `backend/tests/unit/tools/test_lost_sales.py` (lost revenue and lost profit separate, censored stockout days, LOW confidence)
- `backend/tests/scenarios/test_nightly_pipeline.py`, `backend/tests/scenarios/test_demo_scenarios.py`
