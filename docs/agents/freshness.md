# Freshness

Key: `freshness` · Group: PIPELINE · Kind: Deterministic · Pattern: PIPELINE_STAGE · Critical: no · Prompt version: none

## Purpose
Expiry risk per batch. Implementation: `FreshnessAgent` in `backend/app/agents/freshness.py`, using
`FreshnessTools` and `TransferDecisionEngine.find_expiry_receivers`.

For batches expiring within `expiry_window_days`: FEFO at-risk units per batch (D-31). At-risk units go first to
other HIGH-confidence stores that can sell them before expiry (single receiver first, D-28) as expiry-aware
transfers. What nobody can sell becomes an `EXPIRY_ALERT` at the holding store (priority HIGH when ≤ 3 days left).

## 4D notes
- **Delegation** — Not an LLM: days-to-sell vs days-to-expiry is arithmetic.
- **Description** — SD-08; `expiry_window_days`, `perishable_max_shelf_life_days`.
- **Discernment** — Scenario 5 (expiry transfer) asserted end to end.
- **Diligence** — Expiry transfers follow the normal transfer approvals.

## System instructions
No LLM decisions. Its recommendations get explanation text later, in the Purchase Orders stage, through
`ExplanationService`.

## Input contract
`RunContext`; batches; forecasts of this run (via `PlanningInputs`).

## Output contract
`TRANSFER` recommendations with `TransferEvidence.expiring_batch`, PROPOSED `transfer_order` rows
(`is_expiry_aware=True`), `EXPIRY_ALERT` recommendations (`ExpiryEvidence`). Decision types: `EXPIRY_TRANSFER`,
`EXPIRY_ALERT_RAISED`. Outputs: `batches_scanned`, `transfers`, `expiry_alerts`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `expiry_risk` (`FreshnessTools.at_risk_by_batch`, `find_expiry_receivers`) | read | at-risk qty per batch; receivers |

Deterministic functions, not LLM tools. Transfers are only PROPOSED. Nothing here approves, submits, dispatches,
receives, changes rules or changes stock.

## State and memory
Within a run: `PlanningInputs`. Across runs: none.

## Stopping conditions
`RunParams.max_steps` per stage; 2 attempts, then FAILED.

## Failure handling
| Failure | Outcome |
|---|---|
| Exception | Retried once; then FAILED and the run is PARTIAL |
| No expiring batches | SUCCESS with zeros; `expiry_scan` logged "no batches" |
| Demand Forecasting did not succeed | `SKIPPED_DEPENDENCY` |

## Human-in-the-loop
Expiry transfers: destination accepts, donor releases.

## When turned off
No expiry transfers or alerts; the inventory screen shows "Expiry checks off".

## Evaluation
- `backend/tests/unit/tools/test_freshness.py` (FEFO, expired batch, no demand)
- `backend/tests/scenarios/test_demo_scenarios.py` (`test_scenario_5_expiry_aware_transfer_of_the_at_risk_units`)
