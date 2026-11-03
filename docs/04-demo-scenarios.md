# Demonstration scenarios = acceptance tests

The synthetic data generator (`data/synthetic/`) must reproduce each scenario deterministically (fixed seed).
Each scenario has an automated test in `backend/tests/scenarios/` that runs the nightly pipeline and asserts the result,
then exercises the approval/transfer API as the right users.

| # | Setup | Expected recommendation | Expected workflow result |
|---|---|---|---|
| 1 | Fast mover (e.g. Rice 5 kg) sells high in all 3 stores; no store has surplus | PO needs for every short store; one consolidated PO per supplier with store-wise lines; reason NO_SURPLUS_IN_ANY_STORE | Each supervisor approves own lines (L1); PO goes to L2 if ≥ threshold; Super Admin approves → SUBMITTED (simulated) |
| 2 | Store A surplus of a SKU; Store C short; transfer cheaper and fast enough | TRANSFER A→C, no PO for C | C accepts → A approves release → re-check OK → dispatch → C receives full qty → ledger TRANSFER_OUT/IN |
| 3 | Store C need 40, holds 0; Store A available 54, requirement 30; Store B no surplus | TRANSFER A→C 24 + PO need C 16 (PARTIAL_SURPLUS) | Evidence shows 24 and 16 separately; both flows complete |
| 4 | Bread reordered in a store; butter has lift ≥ 1.5 with bread and will run short before next delivery | CO_REPLENISH recommendation for butter, linked to bread, rule shown as evidence | Butter appears as its own line in the PO |
| 5 | Batch in Store A expires before A can sell it; Store C can sell it in time | Expiry-aware TRANSFER of that batch A→C | Batch moves to Store C on receipt; if no receiver, EXPIRY_ALERT (markdown is an extension) |

Additional edge-case tests:
- Store B rejects its lines on a consolidated PO while Store A approves → child PO with A's lines continues.
- l1_deadline passes with a store undecided → lines ESCALATED (default) and visible to Super Admin.
- Surplus disappears between proposal and donor approval → transfer CANCELLED, need carried forward.
- Received qty < sent → discrepancy recorded, stock correct in both stores.
- Store Supervisor requests another store's inventory → 403.
- POS snapshot differs from ledger → ADJUSTMENT movement + evidence logged.
- Redis down → dashboard still served from PostgreSQL.
