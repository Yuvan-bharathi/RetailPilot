# Agent patterns vs deterministic baselines (Objective III, docs/08 §8)

Source data: `docs/notes/agent-eval-report.md` (RECORDED run of `python -m scripts.run_agent_evals`, 53 cases × 2
variants on the synthetic small dataset). Each agent and its baseline ran on the same inputs.

## Read this first — what the numbers can and cannot tell

- The AGENT rows come from **scripted model replays**: the model turns are hand-written. They prove the
  machinery — tool allow-list, structured output and its validation, stopping conditions, code checks
  (grounding, donor protection, scoping, allow-listed actions) and the fail-safe paths — on real data. They do
  **not** measure how well the live model chooses tools or words answers. The AGENT correctness of 100% is
  therefore "every safeguard behaved as designed", not "the model is always right".
- BASELINE correctness is scored against the same case expectations. Several expectations need a behaviour only
  an agent has (a prose answer citing a business rule; classifying a mismatch as OTHER). A low baseline score
  shows what the baseline *cannot do*, not that it makes mistakes: every baseline output was grounded (100%).
- A live comparison (`--live`, Groq `openai/gpt-oss-120b`) is the decision-grade measurement. It is manual and
  costs tokens; it has **not been run** for this report (no approval for the spend yet; the shared Groq key also
  hit rate limits during development). Human agreement is pending: no reviewer labels yet
  (`backend/tests/agent_evals/human_review.json`).

| Pattern | Agent correct / grounded | Baseline correct / grounded | Agent tokens per case (est.) | p95 agent / baseline (scripted, local DB) |
|---|---|---|---|---|
| Retrieval — Ask RetailPilot | 100% / 92%¹ | 50% / 100% | ≈ 1.6k | 16 / 16 ms |
| Validation — Data Quality | 100% / 100% | 9% / 100% | ≈ 5.5k | 187 / 92 ms |
| Action — Replenishment Action | 100% / 100% | 40% / 100% | ≈ 2.3k | 109 / 109 ms |
| Coordinator — Run Coordinator | 100% / 100% | 50% / 100% | ≈ 1.7k | 46 / 47 ms |
| Reviewer — Recommendation Reviewer | 100% / 100% | 60% / 100% | ≈ 1.2k | 16 / 16 ms |

¹ The one ungrounded AGENT case is `hallucinated_number`: the scripted model invents "98765 units"; the code
check rejects it and the user gets the retrieval-only answer. That is the intended outcome (counted as correct).

Latency of scripted runs excludes model time; a live call adds roughly 1–5 s per model turn (not measured here).

## Per pattern

### 1. Retrieval — Ask RetailPilot → **adopt (pilot)**
- *Agent earns its place:* open questions ("Why are we ordering butter?", "What is the L2 threshold?") need a
  choice of source (recommendation evidence, business rules, policy sections) and a short answer. The baseline can
  only list matching records; it cannot answer a rules question or explain evidence in words (50%).
- *Safety:* read-only tools, store scoping inside the tools, citations must be ids a tool returned, every number
  must appear in a tool result, consequential requests refused before any model call. If any check fails the
  user gets the retrieval-only answer — never an unchecked one.
- *Retrieval decision:* PostgreSQL full-text search is enough for 26 policy sections and product-name lookups;
  pgvector is **not** added. Revisit only if the live eval shows FTS misses (e.g. synonyms such as "dahi"/"curd").
- *Cost:* ≈ 1.6k tokens per question ≈ $0.0004 at gpt-oss-120b prices.

### 2. Validation — Data Quality → **adopt with the baseline kept as fallback**
- The SD-02 rules already flag stale SKUs and mismatches; the agent adds a likely cause, severity and a next step,
  and groups signals. Evidence ids are enforced in code (an issue without returned evidence is dropped).
- Value depends on wording quality, which only the live eval and human labels can judge. Low cost (runs only when
  ingestion has signals; ≈ 5k tokens). Keep it non-critical; the baseline report is used whenever the model fails.

### 3. Action — Replenishment Action → **do not adopt for production yet**
- On this dataset the deterministic engine already produces the right transfer-or-PO split (rules 2–5); the
  baseline's lower score comes from cases built around wrong model proposals, which the code checks reject.
- With the code checks the agent can only propose what the deterministic tools allow (qty from tool results,
  donor protection) — so its extra value over `ra_baseline` is the rationale text. The synthetic data produced no
  NEEDS_REVIEW lines in the demo run, so the exception case it targets is rare here.
- Keep it available (drafts only, human decides) and re-evaluate when real exception volumes are known.

### 4. Coordinator — Run Coordinator → **keep the deterministic orchestrator as primary; agent optional**
- Clean runs never call the model (short-circuit). On failures the agent can pick a retry for a transient error
  where SD-01 would only mark the run PARTIAL. Every action is allow-listed in code: critical agents are never
  retried by the coordinator, at most one retry per stage, at most 3 actions.
- Failures are rare and the SD-01 policy is predictable; the agent's gain is small. Recommended setting: off in
  production until the live eval shows its retry choices beat "mark partial + escalate".

### 5. Reviewer — Recommendation Reviewer → **adopt the code checks always; LLM judge on a sample**
- The new code checks (numbers, donor protection, transfer + remainder = need, no other-store stock in the text)
  run on every recommendation at no cost and catch more than the old number-match (baseline 60%).
- The LLM judge only adds wording issues (unsupported claims such as "urgent") on a sample (40 per run, batches of
  20) to bound cost. When it fails, items are judged by code only and still labelled.

## Overall conclusion
Numbers stay deterministic everywhere (rule 11). Two agents clearly add a capability the application lacks
(Ask RetailPilot, the Reviewer's checks); Data Quality is a cheap, safe addition; Replenishment Action and Run
Coordinator are built, safe and observable, but application logic is sufficient for now — they are not adopted
as default-on in production until a live evaluation and human review show a benefit. Every agent can be switched
off individually, and all of them with the global LLM switch, without affecting the deterministic pipeline.
