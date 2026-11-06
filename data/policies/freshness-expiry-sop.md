# Freshness and Expiry SOP

## Expiry risk
For every batch, days to sell at current demand are compared with days to expiry within the expiry window business
rule. Batches that will not sell in time are at risk.

## Expiry transfers
If another store can sell an at-risk batch before it expires, RetailPilot proposes an expiry transfer. It follows
the normal transfer approval steps.

## Expiry alerts
If no store can sell the batch in time, an expiry alert is raised for the store supervisor. Markdown rules are a
later extension and are not active.

## Write-offs
Expired stock is removed with an EXPIRY_WRITE_OFF movement in the inventory ledger. Quantities are never edited
directly.
