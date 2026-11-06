# Demand Forecasting

Key: `demand_forecasting` · Group: PIPELINE · Kind: Deterministic · Pattern: PIPELINE_STAGE · Critical: yes · Prompt version: none

## Purpose
Daily demand per store-SKU with a method and HIGH/LOW confidence (D-45). Implementation: `DemandForecastingAgent`
in `backend/app/agents/forecasting.py`, using `ForecastTools` (`app/tools/forecast.py`).

Steps in the code:
1. Daily net sale units per store-SKU over `forecast_lookback_days`, zero-filled (returns and voids excluded).
2. Stockout days (`closing_on_hand <= 0`) are flagged and excluded from the estimate (D-30).
3. ABC/XYZ per store-SKU, written to `store_product` in one bulk update.
4. Baseline = mean daily demand over the in-stock days of the last `kpi_lookback_days`.
5. Model selection only when `use_model_selection` is on (off by default, D-45): a backtest picks a model per
   store-SKU only when it beats the baseline.

Confidence is LOW for stale SKUs (from ingestion) or fewer than 7 in-stock days (`MIN_IN_STOCK_DAYS`).

## 4D notes
- **Delegation** — Not an LLM: forecasting is a numeric model; an LLM adds no accuracy.
- **Description** — SD-04, spec §8. Rules: `min_history_days`, `stale_days`.
- **Discernment** — 28-day replay evaluation (`docs/EVALUATION_REPORT.md`), WMAPE and bias per method.
- **Diligence** — LOW confidence never auto-transfers: Stock Balancing routes it to NEEDS_REVIEW (D-04).

## System instructions
No LLM decisions and no explanation text.

## Input contract
`RunContext`; sales history of `forecast_lookback_days`; stale SKUs from ingestion (`ctx.stale_skus`).

## Output contract
`forecast` rows (`daily_demand`, `method`, `confidence`, `horizon_days`). `AgentResult.outputs`: `forecasts`,
`low_confidence`, `methods`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `forecast_demand` (`ForecastTools.*`) | read | daily demand, method, in-stock days per store-SKU |

Deterministic functions, not LLM tools. Nothing here approves, submits, dispatches, receives, changes rules or
changes stock.

## State and memory
Within a run: in-memory series only. Across runs: none; writes `forecast` rows for its `run_id` and updates
`store_product.abc_class` / `xyz_class`.

## Stopping conditions
`RunParams.max_steps` per stage; 2 attempts, then FAILED.

## Failure handling
| Failure | Outcome |
|---|---|
| Exception in the agent | Retried once; then FAILED. Critical: later stages are `SKIPPED_DEPENDENCY` and the run is FAILED |
| No sales in the lookback | SUCCESS with 0 forecasts |
| Run Coordinator | Never retries this agent (critical); it may ESCALATE |

## Human-in-the-loop
None directly; LOW confidence items reach humans as NEEDS_REVIEW.

## When turned off
Critical: nightly replenishment is PAUSED — only `data_quality` and `sales_analytics` run, nothing is superseded, the
cache is not switched, users keep the last results. Turning it off needs double confirmation.

## Evaluation
- `backend/tests/unit/tools/test_forecast.py`, `backend/tests/unit/tools/test_forecast_models.py`
- `backend/tests/unit/synthetic/test_replay_evaluation.py` and `docs/EVALUATION_REPORT.md`
- `backend/tests/scenarios/test_demo_scenarios.py` (`test_stale_sku_is_low_confidence`)
