# Stock Balancing

Key: `stock_balancing` · Group: PIPELINE · Kind: Deterministic · Pattern: PIPELINE_STAGE · Critical: yes · Prompt version: none

## Purpose
Requirement, surplus, transfer-vs-PO on incremental costs, donor protection and co-replenishment. Implementation:
`StockBalancingAgent` in `backend/app/agents/stock_balancing.py`, using `RequirementCalculator` and
`TransferDecisionEngine`.

- Per listed store-SKU: own requirement (rule 1, lead time of the supplier serving that store) and available.
- LOW-confidence store-SKUs are neither donors nor receivers; if short → `REORDER` with status NEEDS_REVIEW and no
  replenishment need (D-04).
- Pass 1 (D-17) marks (supplier, store) pairs that need a PO anyway; products are decided by urgency (shortest days
  of cover first): transfers of genuine surplus, PO needs for the remainder (rules 2–5).
- Co-replenishment: complements from this run's rules with lift ≥ `co_replenish.min_lift`, at most
  `co_replenish.limit` per product, only if that supplier already delivers to the store this cycle.

Worked example (registry): Store C needs 40, Store A has surplus 24 → transfer 24 + PO 16.

## 4D notes
- **Delegation** — Not an LLM: rules 1–5 are exact formulas.
- **Description** — SD-06, SD-07. Cost parameters come from `BusinessRule` via `RunParams`.
- **Discernment** — Property tests: a donor never goes below its own requirement; costs are incremental only.
- **Diligence** — Every recommendation carries validated D-34 evidence, also in `decision_evidence`.

## System instructions
No LLM decisions. Its recommendations get explanation text later, in the Purchase Orders stage, through
`ExplanationService` (any number not in the evidence is rejected and the template is used).

## Input contract
`RunContext`; forecasts of this run (required); lost sales and association rules of this run when present.

## Output contract
`TRANSFER` / `REORDER` / `CO_REPLENISH` recommendations, `replenishment_need` rows (SHORTFALL / CO_REPLENISH),
PROPOSED `transfer_order` rows. Decision types: `TRANSFER_CHOSEN_OVER_PO`, `PO_NEED_CREATED`,
`CO_REPLENISH_LINKED`, `NEEDS_REVIEW_RAISED`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `requirement` (`RequirementCalculator`) | read | requirement, surplus, co-replenish qty |
| `transfer_decision_engine` (`TransferDecisionEngine`) | read | transfers and PO needs per product |

Deterministic functions, not LLM tools. Transfers are only PROPOSED. Nothing here approves, submits, dispatches,
receives, changes rules or changes stock.

## State and memory
Within a run: `PlanningInputs` and the `planned` (supplier, store) set. Across runs: none; outputs keyed by `run_id`.

## Stopping conditions
`RunParams.max_steps` per stage; 2 attempts, then FAILED.

## Failure handling
| Failure | Outcome |
|---|---|
| Exception | Retried once; then FAILED. Critical: later stages `SKIPPED_DEPENDENCY`, run FAILED |
| Demand Forecasting did not succeed | `SKIPPED_DEPENDENCY` |
| Optional input missing | Runs; `input_missing` WARN names the missing agent |
| No serving supplier for a store-SKU | Skipped here; left to the PO agent |

## Human-in-the-loop
Transfer: destination accepts → donor releases. PO need: L1 per store, L2 above the threshold.

## When turned off
Critical: nightly replenishment is PAUSED (double confirmation to turn off). Freshness is not affected by the
dependency, but it is skipped while paused.

## Evaluation
- `backend/tests/unit/tools/test_transfer_engine_properties.py` (`test_no_donor_ends_below_its_own_requirement`)
- `backend/tests/unit/tools/test_requirement.py`, `test_transfer_engine.py`, `test_cost_model.py`
- `backend/tests/scenarios/test_demo_scenarios.py` (scenarios 1–4)
