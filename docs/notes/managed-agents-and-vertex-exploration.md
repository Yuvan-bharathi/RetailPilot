# Exploration: Claude Managed Agents and GCP Vertex AI agent runtime (docs/08 §3)

Status: **documented only — no prototype.** Per D-53 the Managed Agents comparison runs on **Anthropic**
(`claude-opus-5-5`, the same model as the application-orchestrated agent, so only the hosting differs). docs/08 allows a prototype only with organisational approval
(Managed Agents) or an approved GCP project (Vertex AI). Neither exists for this project, and the product's LLM
provider is Groq (D-44). Feature details below must be re-checked against current vendor documentation before
any prototype; nothing here is assumed to be available to this organisation.

## Candidate: pattern 1 (Ask RetailPilot) — the same agent hosted three ways

| | Application-orchestrated (built) | Claude Managed Agents (not built) | Vertex AI agent runtime (not built) |
|---|---|---|---|
| Loop | our `ToolLoopAgent` (framework.py) | vendor-hosted agent loop | Google-hosted agent runtime |
| Tools | Python functions, scoped by `ToolContext` | host-side custom tools (our process answers each tool call, scoped per user) or our MCP server reachable over the network | tools as HTTP/MCP endpoints of our FastAPI service |
| Scoping (rule 10) | inside each tool, from the caller | must be enforced by the MCP server per user/session — needs per-user auth on the MCP connection | same: per-user token passed to our tool endpoint |
| Logging | AgentRunLogger → agent console | vendor logs + our MCP server's tool-call log | Cloud Logging/Trace + our tool log |
| Stopping / structured output | our code (limits, submit tool, Pydantic) | vendor settings; we validate the final answer again | runtime settings; we validate again |
| Data residency | our PostgreSQL + Groq | Anthropic + our MCP server | GCP region + our DB |

## What a prototype would measure
Setup effort (hours), control (can we enforce the allow-list and stopping conditions ourselves?), observability
(can each tool call appear in the agent console?), cost per question and p50/p95 latency on the same 12 Ask cases
(`backend/tests/agent_evals/cases.py`).

## Integration sketch
1. Keep `retailpilot-tools` (backend/app/agents/llm/mcp_server.py) as the single tool surface; run it as a
   network service with per-user auth instead of stdio.
2. FastAPI `/assistant/ask` calls the hosted agent instead of `answer_question`, then applies the same code checks
   (citations ⊆ returned ids, numbers ⊆ tool results) before returning — the safety net stays ours.
3. Log the hosted run id on the `agent_run` row so the console links to the vendor trace.

## Recommendation
Not needed for the PoC: the application-orchestrated agent already meets the brief with full control and logging.
Revisit if the organisation standardises on a hosted agent platform.
