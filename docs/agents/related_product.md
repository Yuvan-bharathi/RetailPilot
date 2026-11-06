# Related Products

Key: `related_product` · Group: PIPELINE · Kind: Deterministic · Pattern: PIPELINE_STAGE · Critical: no · Prompt version: none

## Purpose
Basket association rules (support, confidence, lift) and assortment gaps. Implementation: `RelatedProductAgent` in
`backend/app/agents/related_products.py`, using `BasketTools` (`app/tools/basket.py`).

Per store, over the last 90 days (`LOOKBACK_DAYS`): clean the bills (returns, voids, bulk bills above the
per-category line limit, promotion days), skip the store when it has fewer than `basket.min_bills` bills, mine rules
with FP-Growth at the configured thresholds, store them as `COMPLEMENT` rules. An assortment gap is a strong rule X→Y
in other stores for a store that lists X but not Y (lift ≥ `co_replenish.min_lift`).

## 4D notes
- **Delegation** — Not an LLM: market-basket statistics are deterministic.
- **Description** — SD-05; `basket.*` business rules.
- **Discernment** — The planted bread→butter pair is recovered in tests (scenario 4).
- **Diligence** — Assortment gaps are recommendations a supervisor accepts or rejects. Skipped stores are logged as WARN.

## System instructions
No LLM decisions. `ASSORTMENT_GAP` recommendations get explanation text later, in the Purchase Orders stage, through
`ExplanationService` (numbers checked against evidence).

## Input contract
`RunContext`; sales lines of the last 90 days; `RunParams.basket` and `co_replenish`.

## Output contract
`association_rule` rows; `ASSORTMENT_GAP` recommendations (`qty` 0, `AssortmentGapEvidence`) with
`decision_evidence` rows. Decision type: `ASSORTMENT_GAP_FOUND`. Outputs: `rules`, `gaps`, `skipped_stores`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `mine_association_rules` (`BasketTools.clean_bills`, `to_basket_matrix`, `mine_rules`, `find_assortment_gaps`) | read | rules per store; gap candidates |

Deterministic functions, not LLM tools. Nothing here approves, submits, dispatches, receives, changes rules or
changes stock.

## State and memory
Within a run: rules per store in memory. Across runs: none; rules are keyed by `run_id`.

## Stopping conditions
`RunParams.max_steps` per stage; 2 attempts, then FAILED.

## Failure handling
| Failure | Outcome |
|---|---|
| Exception | Retried once; then FAILED and the run is PARTIAL |
| Too few bills in a store | Store skipped and logged (`mine_rules` tool call with status WARN) |
| No rules / no listings | 0 rules or 0 gaps; SUCCESS |

## Human-in-the-loop
Assortment gaps: supervisor accept / reject in the inbox.

## When turned off
No co-replenishment and no assortment gaps. Stock Balancing runs without them and says so in its run log
(`input_missing` WARN).

## Evaluation
- `backend/tests/unit/tools/test_basket.py` (`test_mine_rules_finds_bread_and_butter`, assortment-gap tests)
- `backend/tests/scenarios/test_demo_scenarios.py` (`test_scenario_4_reorder_with_co_replenished_complement`)
