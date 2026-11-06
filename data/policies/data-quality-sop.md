# Data Quality SOP

## Stale SKUs
A SKU is stale when the store holds stock but no sale was recorded for more than the stale days business rule.
Common causes: the item is not on the shelf, the POS item code is mapped to another product, or the product is
seasonal. Check shelf placement and the POS item mapping first.

## Snapshot mismatches
When the POS closing stock differs from the ledger, a reconciliation adjustment is recorded. Repeated adjustments
for the same product suggest unrecorded wastage, theft or a receiving error. Review them with the store supervisor.

## Who fixes data
Agents never change stock or sales data. Corrections go through the inventory ledger by authorised people.

## Agent review items
The Data Quality agent may create review items with evidence for the Super Admin. A review item is a draft: it
changes nothing until a person acts on it.
