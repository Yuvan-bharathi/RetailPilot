# Purchase Order Approval Policy

## Consolidated purchase orders
RetailPilot consolidates the needs of all stores served by one supplier into one purchase order. Each line belongs
to one store.

## Level 1 approval by store supervisors
Each store supervisor approves, edits or rejects the pending lines of their own store before the Level 1 deadline.
A rejection needs a written reason. Lines not decided by the deadline are escalated to the Super Admin (default) or
expire, depending on the business rule.

## Escalated lines
The Super Admin decides escalated lines; the decision is recorded as the Level 1 decision for that store.

## Level 2 approval
Level 1 is final only when no line is pending or escalated. Approved lines continue as a child purchase order. If
its value is above the Level 2 threshold (a business rule, `po_l2_threshold`), the Super Admin must approve it at
Level 2 before it is submitted.

## Submission
Approved and submitted lines count as incoming stock until goods receipt. In the PoC no real supplier order is
sent: the supplier gateway is simulated.

## Superseded orders
Each nightly run marks undecided Level 1 purchase orders of the previous run as superseded; the new run proposes
fresh quantities.
