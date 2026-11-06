# Data Quality

Key: `data_quality` · Group: OBJECTIVE_III · Kind: LLM · Pattern: VALIDATION · Critical: no · Prompt version: `data_quality.v1`

## Purpose
Triages ingestion results (stale SKUs, snapshot mismatches, anomalies) into a likely cause and a next step, and
proposes data-review items with evidence. Code: `triage` and `DataQualityAgent` in
`backend/app/agents/llm/agents.py`. First nightly stage, after ingestion.

## 4D notes
- **Delegation** — Mixed signals → a cause and next step is interpretation. The SD-02 rules only flag.
- **Description** — Prompt `data_quality.v1`; output `DQReport` (the registry calls it DataQualityReport).
- **Discernment** — Each issue must cite `evidence_ids` returned by `get_ingestion_report`; code drops any issue with
  an unknown id (`rejected_issues`). The category must be one of the allowed list (Pydantic `Literal`).
- **Diligence** — It can only create `DATA_REVIEW_ITEM` drafts; it never edits stock or sales (rule 8). Every kept
  issue is an `agent_decision` (`DATA_ISSUE_CLASSIFIED`).

## System instructions
`backend/app/agents/llm/prompts/data_quality.v1.md`. Call `get_ingestion_report`, optionally
`get_inventory_position` or `get_run_log`; group signals into at most 10 issues with category, cause, severity and
one next step; call `submit_report`. No evidence → no issue. Copy numbers, never invent. HIGH only when replenishment
decisions are likely wrong.

## Input contract
`RunContext` (run date). In the nightly run the `ToolContext` has role SUPER_ADMIN, no store, `scope_run_id` = this
run. The input data is the latest ingestion report.

## Output contract
`DQReport`: `summary` (3–400 chars), `issues` (max 10) of `DQIssue`:

| Field | Type |
|---|---|
| `category` | STALE_SKU, SNAPSHOT_MISMATCH, SALES_ANOMALY, MISSING_DATA, OTHER |
| `likely_cause` | str, 5–300 |
| `severity` | LOW, MEDIUM, HIGH |
| `evidence_ids` | list[str], 1–10 |
| `next_step` | str, 5–300 |

Persisted: `agent_draft` rows (`DATA_REVIEW_ITEM`) for MEDIUM and HIGH issues. Stage outputs: `mode`, `issues`,
`drafts`, `rejected_issues`, `summary`, `stop_reason`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `get_ingestion_report` | read | latest POS day signals with `evidence_id` (`stale:…`, `adjustment:…`), store-scoped |
| `get_inventory_position` | read | stock position of a product |
| `get_run_log` | read | stages, statuses, errors of a run (Super Admin only) |
| `create_data_review_item` | draft-write | an `agent_draft` DATA_REVIEW_ITEM; rejects ids not from `get_ingestion_report` |

The model loop gets the full list, but drafts are created by code after validation. No tool approves, submits,
dispatches, receives, changes rules or changes stock.

## State and memory
Within a run: `ToolContext.cache["ingestion_evidence"]` (known evidence ids), `seen_ids`, `seen_numbers`.
Across runs: none. Persisted: `agent_draft`, `agent_decision` (`DATA_ISSUE_CLASSIFIED`, `NEEDS_REVIEW_RAISED`),
`tool_call`, `llm_usage`.

## Stopping conditions
- `submit_report` called with a valid `DQReport`.
- Max 10 tool calls, 16,000 tokens, 60 s, 10 turns; one nudge then `no_submit`.
- No ingestion issues → returns "No ingestion issues" without an LLM call.

## Failure handling
| Failure | Outcome |
|---|---|
| Tool error | Error text to the model; loop continues |
| Empty data | No issues → empty report, no LLM call |
| Invalid input (unknown evidence id) | Issue dropped and counted in `rejected_issues`; draft tool refuses |
| Invalid model output | One retry; then `invalid_output` → baseline |
| Model error / timeout / token budget / no key | `dq_baseline`: one issue per signal type with fixed wording; severity by count |

## Human-in-the-loop
Super Admin reviews data-review items.

## When turned off
Ingestion flags are shown as rule-based flags only (SD-02); no triage. Stage is `SKIPPED_DISABLED` ("all LLM agents
off" when the global switch is off). It runs even while replenishment is PAUSED.

## Evaluation
`backend/tests/agent_evals/cases.py` (`DQ_CASES`: 11 cases incl. invented evidence, invalid category, token budget,
no submit, tool loop cap, cannot edit stock) and `docs/notes/agent-eval-report.md`.
