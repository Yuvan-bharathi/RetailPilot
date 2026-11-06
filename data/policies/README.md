# Synthetic SOP and policy documents (D-50)

Written for the Ask RetailPilot retrieval agent (docs/08 §6). Synthetic — they restate the frozen business rules
(docs/01, CLAUDE.md rules 1–11) in operational language and never introduce a new rule. Numbers that are business
parameters are NOT written here: the agent reads them from the business_rule table (`get_business_rules`).
Each `## ` section is one searchable unit (`policy_document`, PostgreSQL full-text search).
