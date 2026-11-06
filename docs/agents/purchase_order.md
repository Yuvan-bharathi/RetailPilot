# Purchase Orders

Key: `purchase_order` · Group: PIPELINE · Kind: Deterministic · Pattern: PIPELINE_STAGE · Critical: yes · Prompt version: none

## Purpose
Consolidated supplier POs from this run's replenishment needs (MOQ, case packs, budget, L1 deadline). Implementation:
`PurchaseOrderAgent` in `backend/app/agents/purchase_order.py`, using `POBuilder` (`app/tools/po_builder.py`).

Steps: pick an eligible supplier per need (lead time for that store); consolidate into draft POs; round to pack/MOQ;
validate against the weekly budget; trim lines that do not fit; set L1 or L2 by `po_l2_threshold`; set `l1_deadline`
from `l1_deadline_hours`. A need with no eligible supplier (D-07) or a line cut by the budget (D-29) moves its own
recommendation to NEEDS_REVIEW with `NeedsReviewEvidence`.

## 4D notes
- **Delegation** — Not an LLM: PO building is deterministic; the LLM only writes explanation text.
- **Description** — SD-09; explanations via `ExplanationService`.
- **Discernment** — `ExplanationService` rejects any LLM text containing a number not in the evidence.
- **Diligence** — Every PO is PENDING_L1 (or DRAFT when validation fails); never sent to a real supplier
  (`SimulatedSupplierGateway`).

## System instructions
No LLM decisions. Explanation text only, via `ExplanationService`: it explains every recommendation of the run and
every new PO, in batches of 20. A text with a number not in the facts, an empty text, no key, the template provider
or an LLM error → the deterministic template (rule 11).

## Input contract
`RunContext`; replenishment needs and recommendations of this run.

## Output contract
`purchase_order` + `po_line` rows (PENDING_L1, lines PENDING), explanations on recommendations and POs. Decision
type: `PO_DRAFTED`. Outputs: `pos`, `needs_review`, `budget_trimmed`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `po_builder` (`POBuilder`) | read | supplier choice, consolidated POs, rounding, budget trim |
| `explain` (`ExplanationService.explain`) | read | explanation text per item (grounded or template) |

Deterministic functions, not LLM tools. Nothing here approves, submits, dispatches, receives, changes rules or
changes stock.

## State and memory
Within a run: remaining weekly budget. Across runs: committed spend of the week is read from earlier POs.

## Stopping conditions
`RunParams.max_steps` per stage; 2 attempts, then FAILED.

## Failure handling
| Failure | Outcome |
|---|---|
| Exception | Retried once; then FAILED. Critical: run FAILED, reviewer `SKIPPED_DEPENDENCY` |
| No needs | SUCCESS with 0 POs |
| No eligible supplier / over budget | Recommendation → NEEDS_REVIEW |
| LLM explanation error or ungrounded | Template text used |

## Human-in-the-loop
L1 line approval per store; L2 above the threshold.

## When turned off
Critical: nightly replenishment is PAUSED.

## Evaluation
- `backend/tests/unit/tools/test_po_builder.py`
- `backend/tests/unit/services/test_explanation_service.py`
- `backend/tests/scenarios/test_demo_scenarios.py` (`test_every_recommendation_has_an_explanation`, scenario 1)
