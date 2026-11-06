# Replenishment Action

Key: `replenishment_action` · Group: OBJECTIVE_III · Kind: LLM · Pattern: ACTION · Critical: no · Prompt version: `replenishment_action.v1`

## Purpose
For exception cases (NEEDS_REVIEW recommendations) it assembles a transfer-or-PO proposal from tool results and
returns a structured DRAFT. It can never approve or submit. Code: `draft_for` and `ReplenishmentActionAgent` in
`backend/app/agents/llm/agents.py`. Depends on `stock_balancing`.

It is not a fixed nightly stage. It runs when the Run Coordinator chooses `INVOKE_REPLENISHMENT_ACTION`, or from
"Run now". Per run it handles at most 10 NEEDS_REVIEW recommendations (`MAX_PER_RUN`).

## 4D notes
- **Delegation** — Exceptions where the rules leave a gap (low-confidence forecast, no eligible supplier) need a
  composed proposal across several tools.
- **Description** — Prompt `replenishment_action.v1`; output `ActionDraft`.
- **Discernment** — `qty` must be one of the quantities a tool returned for that `rec_id` (`ToolContext.allowed_qty`:
  need, rec qty, `min(need, surplus)`, remainder). Donor protection is re-checked in code: a transfer qty above the
  donor's surplus is refused (rule 3). A proposal for another `rec_id` is ignored.
- **Diligence** — `create_draft_recommendation` is the only write; code calls it, not the model. Drafts reach a human
  through the existing recommendation / transfer / PO approvals. Each draft is an `agent_decision` (`DRAFT_CREATED`).

## System instructions
`backend/app/agents/llm/prompts/replenishment_action.v1.md`. Call `get_recommendation`, `get_evidence`,
`get_transfer_options`; choose one action: TRANSFER_DRAFT (qty = min(need, surplus)), PO_DRAFT (qty = need) or
NO_ACTION. Quantities only from tool results. If no store has surplus → PO, never transfer (rule 2). Mention low
confidence in the rationale.

## Input contract
`rec_id` of a NEEDS_REVIEW recommendation; in batch mode, the NEEDS_REVIEW recommendations of `scope_run_id`.

## Output contract
`ActionDraft`: `rec_id`, `action` (TRANSFER_DRAFT, PO_DRAFT, NO_ACTION), `qty` (≥ 0), `from_store_id` (optional),
`rationale` (10–600 chars). Persisted via `DraftArgs` (`qty` ≥ 1) as an `agent_draft` row with `draft_type`
TRANSFER_DRAFT or PO_DRAFT, status DRAFT. Stage outputs: `needs_review`, `drafts`, `modes`, `rejected_by_code_checks`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `get_recommendation` | read | one recommendation; seeds `allowed_qty` from qty and evidence quantities |
| `get_evidence` | read | evidence, scoped |
| `get_inventory_position` | read | stock position of a product |
| `get_transfer_options` | read | `need_qty`, own requirement, available, `low_confidence`, donors with surplus > 0 (not LOW confidence) from `RequirementCalculator` |
| `get_business_rules` | read | global rules |
| `create_draft_recommendation` | draft-write | an `agent_draft`; refuses qty not from a tool and qty above donor surplus |

The model loop gets only the read tools; code performs the draft write after validation. No tool approves, submits,
dispatches, receives, changes rules or changes stock.

## State and memory
Within a run: `ToolContext.allowed_qty` per rec_id, `cache["donor_surplus"]`, `cache["planning:<run_id>"]`
(`PlanningInputs`), `seen_ids`, `seen_numbers`. Across runs: none. Persisted: `agent_draft`, `agent_decision`.

## Stopping conditions
- `submit_draft` called with a valid `ActionDraft`.
- Max 8 tool calls, 16,000 tokens, 60 s, 10 turns; one nudge then `no_submit`.
- No viable option → `NO_ACTION` (no draft).

## Failure handling
| Failure | Outcome |
|---|---|
| Tool error | Error text to the model; loop continues |
| Empty data (need is 0) | `NO_ACTION`, no draft |
| Invalid input (unknown / other-store rec_id) | "recommendation not found"; no draft, error recorded |
| Qty not from a tool, or above donor surplus | `ToolError` from the code check; no draft, error in `rejected_by_code_checks` |
| Invalid model output | One retry; then `invalid_output` → `ra_baseline` |
| Model error / timeout / no key | `ra_baseline`: largest donor surplus covers `min(need, surplus)`, else PO for the need |
| Model skipped the tools | Code loads the facts before validating |

## Human-in-the-loop
Draft → supervisor decision on the recommendation (accept / edit / reject).

## When turned off
No agent drafts; NEEDS_REVIEW items are decided manually. A coordinator `INVOKE_REPLENISHMENT_ACTION` is recorded as
"skipped (agent disabled)".

## Evaluation
`backend/tests/agent_evals/cases.py` (`RA_CASES`: 10 cases incl. invented quantity, donor protection violation,
wrong rec_id, unknown recommendation, dispatch refused) and `docs/notes/agent-eval-report.md`.
