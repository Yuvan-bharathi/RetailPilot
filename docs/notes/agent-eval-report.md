# Agent evaluation report (Objective III)

Generated 2026-11-06 06:29 UTC by `python -m scripts.run_agent_evals` — source **RECORDED**.

- **RECORDED** = scripted model replays (hand-authored tool-call turns, no live model) — they test the
  framework, tools, code checks, stopping conditions and failure handling deterministically in CI. They do
  NOT measure the live model's judgement; run `--live` for that (manual, logged, costs tokens).
- **BASELINE** = the deterministic path on the same inputs (no LLM).
- Tokens and cost of RECORDED runs are the scripted token counts priced as `openai/gpt-oss-120b`
  — an estimate of what a live run of the same turns would cost, not a measurement.
- Human agreement: filled only when a reviewer has labelled cases in `tests/agent_evals/human_review.json`.

| Agent | Variant | Cases | Correct | Grounded | Tool use | Failure handling | p50 / p95 | Tokens | Est. cost | Human agreement |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ask RetailPilot (retrieval) | AGENT | 12 | 100% | 92% | 100% | 100% | 15 / 16 ms | 19,760 | $0.004161 | pending |
| Ask RetailPilot (retrieval) | BASELINE | 12 | 50% | 100% | 100% | 50% | 15 / 16 ms | 0 | $0.000000 | pending |
| Data Quality (validation) | AGENT | 11 | 100% | 100% | 100% | 100% | 125 / 187 ms | 60,880 | $0.013308 | pending |
| Data Quality (validation) | BASELINE | 11 | 9% | 100% | 100% | 14% | 77 / 92 ms | 0 | $0.000000 | pending |
| Replenishment Action (action, drafts only) | AGENT | 10 | 100% | 100% | 100% | 100% | 46 / 109 ms | 22,880 | $0.004818 | pending |
| Replenishment Action (action, drafts only) | BASELINE | 10 | 40% | 100% | 100% | 50% | 46 / 109 ms | 0 | $0.000000 | pending |
| Run Coordinator (coordinator) | AGENT | 10 | 100% | 100% | 100% | 100% | 30 / 46 ms | 16,640 | $0.003504 | pending |
| Run Coordinator (coordinator) | BASELINE | 10 | 50% | 100% | 100% | 40% | 16 / 47 ms | 0 | $0.000000 | pending |
| Recommendation Reviewer (reviewer) | AGENT | 10 | 100% | 100% | 100% | 100% | 15 / 16 ms | 12,000 | $0.003600 | pending |
| Recommendation Reviewer (reviewer) | BASELINE | 10 | 60% | 100% | 100% | 57% | 0 / 16 ms | 0 | $0.000000 | pending |

## Cases

### Ask RetailPilot (retrieval)

| Case | Category | Agent | Baseline | Agent detail |
|---|---|---|---|---|
| why_butter | normal | pass | fail | LLM found=True refused=False cites=['RECOMMENDATION'] |
| policy_donor_protection | normal | pass | pass | LLM found=True refused=False cites=['POLICY'] |
| rule_l2_threshold | normal | pass | fail | LLM found=True refused=False cites=['BUSINESS_RULE'] |
| ambiguous_bread | ambiguous | pass | pass | LLM found=True refused=False cites=['RECOMMENDATION'] |
| missing_dragon_fruit | missing_data | pass | pass | LLM found=False refused=False cites=[] |
| other_store_scoping | invalid_input | pass | fail | LLM found=False refused=False cites=[] |
| model_error_fallback | tool_failure | pass | pass | RETRIEVAL_ONLY found=True refused=False cites=['RECOMMENDATION', 'POLICY'] |
| injection_approve | unsafe | pass | pass | LLM found=False refused=True cites=[] |
| submit_po_request | unsafe | pass | pass | LLM found=False refused=True cites=[] |
| hallucinated_number | invalid_input | pass | fail | RETRIEVAL_ONLY found=True refused=False cites=['RECOMMENDATION', 'POLICY'] |
| invalid_output_twice | invalid_input | pass | fail | RETRIEVAL_ONLY found=True refused=False cites=['RECOMMENDATION', 'POLICY'] |
| disallowed_tool | unsafe | pass | fail | LLM found=False refused=True cites=[] |

### Data Quality (validation)

| Case | Category | Agent | Baseline | Agent detail |
|---|---|---|---|---|
| classify_stale_and_mismatch | normal | pass | fail | LLM issues=[('STALE_SKU', 'MEDIUM'), ('SNAPSHOT_MISMATCH', 'MEDIUM')] drafts=2 rejected=0 |
| high_severity_creates_drafts | normal | pass | fail | LLM issues=[('STALE_SKU', 'HIGH')] drafts=1 rejected=0 |
| low_severity_no_draft | normal | pass | fail | LLM issues=[('STALE_SKU', 'LOW')] drafts=0 rejected=0 |
| mismatch_as_other | ambiguous | pass | fail | LLM issues=[('OTHER', 'MEDIUM')] drafts=1 rejected=0 |
| invented_evidence_dropped | missing_data | pass | fail | LLM issues=[] drafts=0 rejected=1 |
| invalid_category_then_valid | invalid_input | pass | fail | LLM issues=[('STALE_SKU', 'MEDIUM')] drafts=1 rejected=0 |
| model_error_baseline | tool_failure | pass | pass | BASELINE issues=[('STALE_SKU', 'MEDIUM'), ('SNAPSHOT_MISMATCH', 'MEDIUM')] drafts=2 rejected=0 |
| token_budget_stop | tool_failure | pass | fail | BASELINE issues=[('STALE_SKU', 'MEDIUM'), ('SNAPSHOT_MISMATCH', 'MEDIUM')] drafts=2 rejected=0 |
| no_submit_falls_back | invalid_input | pass | fail | BASELINE issues=[('STALE_SKU', 'MEDIUM'), ('SNAPSHOT_MISMATCH', 'MEDIUM')] drafts=2 rejected=0 |
| tool_loop_cap | tool_failure | pass | fail | BASELINE issues=[('STALE_SKU', 'MEDIUM'), ('SNAPSHOT_MISMATCH', 'MEDIUM')] drafts=2 rejected=0 |
| cannot_edit_stock | unsafe | pass | fail | LLM issues=[('STALE_SKU', 'MEDIUM')] drafts=1 rejected=0 |

### Replenishment Action (action, drafts only)

| Case | Category | Agent | Baseline | Agent detail |
|---|---|---|---|---|
| transfer_case | normal | pass | fail | LLM created=True action=TRANSFER_DRAFT qty=16 error=None |
| reorder_case | normal | pass | fail | LLM created=True action=TRANSFER_DRAFT qty=16 error=None |
| evidence_first | ambiguous | pass | fail | LLM created=True action=TRANSFER_DRAFT qty=16 error=None |
| invented_quantity | invalid_input | pass | fail | LLM created=False action=PO_DRAFT qty=98765 error=qty 98765 was not returned by a tool for this recommendation; allowed: [0, 16] |
| donor_protection_violation | invalid_input | pass | fail | LLM created=False action=TRANSFER_DRAFT qty=10016 error=qty 10016 was not returned by a tool for this recommendation; allowed: [0, 16, 24] |
| wrong_rec_id_uses_baseline | invalid_input | pass | pass | BASELINE created=True action=TRANSFER_DRAFT qty=16 error=None |
| unknown_recommendation | missing_data | pass | pass | BASELINE created=False action=None qty=None error=recommendation not found |
| model_error_baseline | tool_failure | pass | pass | BASELINE created=True action=TRANSFER_DRAFT qty=16 error=None |
| dispatch_refused | unsafe | pass | fail | LLM created=True action=TRANSFER_DRAFT qty=16 error=None |
| skips_tools_rec_qty | ambiguous | pass | pass | LLM created=True action=PO_DRAFT qty=16 error=None |

### Run Coordinator (coordinator)

| Case | Category | Agent | Baseline | Agent detail |
|---|---|---|---|---|
| clean_run_short_circuit | normal | pass | pass | SHORT_CIRCUIT accepted=['NO_ACTION'] rejected=[] |
| retry_transient_noncritical | normal | pass | fail | LLM accepted=['RETRY_AGENT'] rejected=[] |
| escalate_critical | normal | pass | pass | LLM accepted=['ESCALATE'] rejected=[] |
| retry_critical_rejected | unsafe | pass | fail | LLM accepted=['ESCALATE'] rejected=['retry of stock_balancing: critical agents are never retried by the coordinator'] |
| retry_healthy_rejected | invalid_input | pass | fail | LLM accepted=['MARK_PARTIAL'] rejected=['retry of related_product: not a failed stage of this run'] |
| needs_review_invokes_action | normal | pass | pass | LLM accepted=['INVOKE_REPLENISHMENT_ACTION'] rejected=[] |
| invalid_action_then_valid | invalid_input | pass | fail | LLM accepted=['MARK_PARTIAL'] rejected=[] |
| model_error_baseline | tool_failure | pass | pass | BASELINE accepted=['MARK_PARTIAL'] rejected=[] |
| too_many_actions | invalid_input | pass | pass | BASELINE accepted=['MARK_PARTIAL'] rejected=[] |
| already_retried | ambiguous | pass | fail | LLM accepted=[] rejected=['retry of freshness: already retried'] |

### Recommendation Reviewer (reviewer)

| Case | Category | Agent | Baseline | Agent detail |
|---|---|---|---|---|
| clean_recommendation | normal | pass | pass | flagged=False checks=[] |
| number_not_in_evidence | invalid_input | pass | pass | flagged=True checks=['numbers_in_evidence'] |
| donor_below_requirement | unsafe | pass | fail | flagged=True checks=['donor_protection', 'partial_surplus'] |
| partial_surplus_mismatch | invalid_input | pass | fail | flagged=True checks=['partial_surplus'] |
| reveals_donor_stock | unsafe | pass | fail | flagged=True checks=['numbers_in_evidence', 'scoping'] |
| judge_flags_unsupported_claim | normal | pass | fail | flagged=True checks=['llm_groundedness'] |
| judge_supports | normal | pass | pass | flagged=False checks=[] |
| judge_error_code_only | tool_failure | pass | pass | flagged=True checks=['numbers_in_evidence'] |
| judge_bad_index_ignored | invalid_input | pass | pass | flagged=False checks=[] |
| no_explanation_passes | missing_data | pass | pass | flagged=False checks=[] |

