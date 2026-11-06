# Applying 4D to our own use of Claude Code (docs/08 §9)

How this project delegates work to the AI coding assistant and keeps it accountable.

## Delegation — what the assistant is asked to do
- Work is cut into phases (PROMPTS.md, phases 0–9, then 5b/6b for the agent layer). Each request names its scope
  (e.g. "UI first, then backend, then data seed"); the assistant does not start a later phase on its own.
- Decisions that are the business's to make are not delegated: business rules are frozen (docs/01, CLAUDE.md
  rules 1–11) and changing one needs explicit approval, recorded in docs/05-decision-log.md.
- Numbers are never delegated to an LLM — not in the product (rule 11) and not in code review: every quantity in
  tests comes from the deterministic tools.

## Description — how the task is described
- CLAUDE.md: stack (fixed), repository layout, the 11 non-negotiable rules, coding conventions, commands.
- Specification and design: docs/01–04 (requirements, technical spec, design system, demo scenarios), docs/06–07
  (HLD/LLD), docs/08–09 (Objective III brief, agent console), PlantUML diagrams (docs/diagrams, CD/SD 1–16).
- Versioned prompts for the product's own LLM agents (backend/app/agents/llm/prompts/*.md) and agent cards
  (docs/agents/) — the same "describe precisely" discipline applied to the agents we build.

## Discernment — how the assistant's output is judged
- Plan review before a phase starts; the decision log records what was decided and why (D-01 … D-5x).
- Tests: unit tests for every pure tool (worked example: need 40, surplus 24 → transfer 24 + PO 16), property
  tests (donor protection), integration tests on PostgreSQL, scenario tests asserting the five demo outcomes,
  Playwright end-to-end tests, vitest + axe accessibility checks, the agent evaluation harness.
- Static checks: ruff, mypy --strict, ESLint, tsc, Prettier, no-hex (design tokens only), API-contract check
  (generated TypeScript must match the FastAPI OpenAPI).
- Screenshot review of UI changes in Chrome; honest reporting of failing or skipped checks.
- Sub-agent output (e.g. the agent cards) is checked against the code; mismatches are fixed in the code or the
  registry, not papered over in docs.

## Diligence — approvals and accountability
- Explicit approval for: business-rule changes, new dependencies (React Flow was not added; a hand-built SVG
  graph was used instead), schema changes outside migrations.
- Commits are local, with clear messages; the assistant never pushes — the owner pushes to GitHub.
- No secrets in the repository; tests never call a live model (LLM_PROVIDER=template is forced in tests).
- The product mirrors this: agents only draft, people approve; every agent run, tool call, LLM call and decision
  is logged and visible in the agent console.
