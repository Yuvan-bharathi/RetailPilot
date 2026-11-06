# Run Coordinator

Key: `run_coordinator` · Group: OBJECTIVE_III · Kind: LLM · Pattern: COORDINATOR · Critical: no · Prompt version: `run_coordinator.v1`

## Purpose
After the deterministic nightly stages, it chooses how to handle failures and exceptions within an allow-list:
retry an agent, mark PARTIAL, escalate to the Super Admin, or invoke Data Quality, Replenishment Action or the
Recommendation Reviewer. Code: `plan_recovery`, `validate_plan`, `RunCoordinatorAgent` in
`backend/app/agents/llm/agents.py`. The orchestrator executes the accepted actions
(`WorkflowOrchestrator._execute_coordinator`).

It runs last, only when the run was not cancelled, replenishment is not PAUSED and the agent is on.

## 4D notes
- **Delegation** — Choosing among recovery paths from logs and context. The deterministic orchestrator (SD-01) stays
  the primary path.
- **Description** — Prompt `run_coordinator.v1`; output `CoordinatorPlan`.
- **Discernment** — `validate_plan` rejects in code: a retry of an unknown agent, of a critical agent, of a stage that
  did not fail in this run, or of a stage already retried. Max 3 actions (Pydantic).
- **Diligence** — It cannot change data. It only invokes registered agents (if they are on) or notifies the Super
  Admin. Every executed action is an `agent_decision`.

## System instructions
`backend/app/agents/llm/prompts/run_coordinator.v1.md`. Call `get_run_log` and `get_exception_summary`, then
`submit_plan` with at most 3 allowed actions and a reason each. Never retry a critical agent: escalate. Timeouts and
transient errors are worth one retry; data or logic errors are not.

## Input contract
The finished nightly run: stage statuses, errors, `critical` flag, `coordinator_retried`, NEEDS_REVIEW count (from
`get_exception_summary`). `ToolContext` role SUPER_ADMIN.

## Output contract
`CoordinatorPlan`: `actions` (1–3) of `PlanAction`:

| Field | Type |
|---|---|
| `action` | RETRY_AGENT, MARK_PARTIAL, ESCALATE, INVOKE_DATA_QUALITY, INVOKE_REPLENISHMENT_ACTION, INVOKE_REVIEWER, NO_ACTION |
| `agent_key` | str or null |
| `reason` | str, 5–300 |

Stage outputs: `mode` (LLM, BASELINE, SHORT_CIRCUIT), `actions` (accepted), `rejected`. Decision types:
`COORDINATOR_RETRY`, `COORDINATOR_ESCALATE`, `COORDINATOR_MARK_PARTIAL`, `COORDINATOR_INVOKE`, `COORDINATOR_NO_ACTION`.

## Allowed tools
| Tool | Kind | Returns |
|---|---|---|
| `get_run_log` | read | root run status and child stages (status, error, critical, retries, coordinator_retried); Super Admin only |
| `get_exception_summary` | read | failed stages, skipped stages, NEEDS_REVIEW count; Super Admin only |

No tool approves, submits, dispatches, receives, changes rules or changes stock.

## State and memory
Within a run: `ToolContext` (`cache["root_run_id"]`, `seen_ids`, `seen_numbers`); accepted actions are passed to the
orchestrator in `ctx.extra["coordinator_actions"]`. Across runs: none; "already retried" is read from the run log
(a second child run of the same agent). Persisted: `agent_decision` per action, `notification` rows for ESCALATE.

## Stopping conditions
- Clean run (no failed stage, no NEEDS_REVIEW) → `NO_ACTION` without an LLM call (`SHORT_CIRCUIT`).
- `submit_plan` called with a valid plan; ≤ 3 actions.
- Max 4 tool calls, 8,000 tokens, 30 s, 10 turns; one nudge then `no_submit`.

## Failure handling
| Failure | Outcome |
|---|---|
| Tool error | Error text to the model; loop continues |
| Empty data (no run) | Empty stages → clean run → `NO_ACTION` |
| Invalid input (disallowed retry) | Action rejected by `validate_plan`, listed in `rejected` |
| Invalid model output (e.g. > 3 actions, unknown action) | One retry; then `invalid_output` → baseline |
| Model error / timeout / no key | `coordinator_baseline`: ESCALATE if a critical stage failed, else MARK_PARTIAL if any failed; INVOKE_REPLENISHMENT_ACTION if NEEDS_REVIEW exist |
| Retried stage fails again | Outcome recorded in the decision summary; the run status stays as it was |

## Human-in-the-loop
Escalations notify the Super Admin (`notification` with a link to the run log).

## When turned off
The deterministic orchestrator handles failures (SD-01): critical failure → FAILED, non-critical → PARTIAL, no
retries beyond the 2 stage attempts.

## Evaluation
`backend/tests/agent_evals/cases.py` (`CO_CASES`: 10 cases incl. retry of a critical agent rejected, already retried,
too many actions) and `docs/notes/agent-eval-report.md`. Also
`backend/tests/scenarios/test_agent_console.py::test_pipeline_and_graph_show_skipped_and_failed_then_retried_stages`.
