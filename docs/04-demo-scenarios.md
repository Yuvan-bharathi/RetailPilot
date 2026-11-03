# Demonstration scenarios = acceptance tests

The synthetic data generator (`data/synthetic/`) must reproduce each scenario deterministically (fixed seed).
Each scenario has an automated test in `backend/tests/scenarios/` that runs the nightly pipeline and asserts the result,
then exercises the approval/transfer API as the right users.

| # | Setup | Expected recommendation | Expected workflow result |
|---|---|---|---|
| 1 | Fast mover (e.g. Rice 5 kg) sells high in all 3 stores; no store has surplus | PO needs for every short store; one consolidated PO per supplier with store-wise lines; reason NO_SURPLUS_IN_ANY_STORE | Each supervisor approves own lines (L1); PO goes to L2 if ≥ threshold; Super Admin approves → SUBMITTED (simulated) |
| 2 | Store A surplus of a SKU; Store C short; transfer cheaper and fast enough | TRANSFER A→C, no PO for C | C accepts → A approves release → re-check OK → dispatch → C receives full qty → ledger TRANSFER_OUT/IN |
| 3 | Store C need 40, holds 0; Store A available 54, requirement 30; Store B no surplus | TRANSFER A→C 24 + PO need C 16 (PARTIAL_SURPLUS) | Evidence shows 24 and 16 separately; both flows complete |
| 4 | Bread reordered in a store; butter has lift ≥ 1.5 with bread; butter is not yet short, but available − daily_demand × review_period < own requirement; butter's preferred supplier is the same supplier that receives the bread PO (D-02) | CO_REPLENISH recommendation for butter, linked to bread, rule shown as evidence | Butter appears as its own line in the PO |
| 5 | Batch in Store A expires before A can sell it; Store C can sell it in time | Expiry-aware TRANSFER of that batch A→C | Batch moves to Store C on receipt; if no receiver, EXPIRY_ALERT (markdown is an extension) |

Additional edge-case tests:
- Store B rejects its lines on a consolidated PO while Store A approves → child PO with A's lines continues.
- l1_deadline passes with a store undecided → lines ESCALATED (default) and visible to Super Admin.
- Surplus disappears between proposal and donor approval → transfer CANCELLED, need carried forward.
- Received qty < sent → discrepancy recorded, stock correct in both stores.
- Store Supervisor requests another store's inventory → 403.
- POS snapshot differs from ledger → ADJUSTMENT movement + evidence logged.
- Redis down → dashboard still served from PostgreSQL.
- (D-01) Escalated lines are decided by the Super Admin (Approval level L1, store_id of the line); the PO finalises
  only after no line is PENDING or ESCALATED; a Store Supervisor deciding after l1_deadline → 409.
- (D-03) Second nightly run supersedes the first run's untouched recommendations / PROPOSED transfers / undecided
  POs (status SUPERSEDED) and does not re-propose surplus already reserved by an accepted transfer.
- (D-03) Transfer accepted → receiver incoming and donor reserved rise by qty; rejected/cancelled → both released.
- (D-04) Stale SKU that is short → NEEDS_REVIEW REORDER recommendation, no PO line, no transfer.
- (D-08) Partial goods receipt → PO_RECEIPT movement, incoming reduced, PO stays SUBMITTED; full receipt → RECEIVED.
- (D-13) Complement whose preferred supplier delivers to another store only (not this one) → no CO_REPLENISH.
- (D-14) PO kept from run 1 with one store decided → its PENDING lines count as on order; run 2 creates no duplicate need.
- (D-15) Donor rejects after destination accepted → REJECTED, reservation and incoming released, destination notified.
- (D-16) Incoming past expected date + grace days → flagged overdue and not counted in available; close-short (Phase 6).
- (D-17) Same input processed twice (shuffled product order) → identical transfer/PO decisions.
