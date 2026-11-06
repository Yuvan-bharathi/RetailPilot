# Replenishment SOP

## Own requirement and available stock
A store's own requirement for a product covers demand until its next delivery: daily demand multiplied by the lead
time of the supplier that serves that store plus the review period, plus safety stock days of demand, plus the
minimum display quantity. Available stock is shelf plus backroom plus incoming minus reserved. Only stock above the
own requirement (surplus) can be offered to another store.

## Transfer before purchase
When one store is short and another of our stores holds genuine surplus, RetailPilot proposes moving the surplus
first. The decision compares only incremental costs: transport and handling of the transfer against the order and
delivery share of a purchase order plus the holding and expiry cost of the donor's surplus. The full purchase price
is never part of the comparison.

## When a product sells high everywhere
If no store has surplus because the product sells high in every store, the shortage is ordered from the supplier.
A transfer is never proposed in that case.

## Partial surplus
When a donor's surplus covers only part of the need, RetailPilot proposes a transfer for the surplus and a purchase
order for the remainder. Both quantities are shown separately so the supervisor can see each part.

## Co-replenishment of related products
Products that are bought together (for example bread and butter) can be restocked together when the related
product is reordered in the same store, its supplier already delivers this cycle and it would fall below its own
requirement before the next review. The basket strength threshold and the limit per product are business rules.

## Low-confidence forecasts
A product with a low-confidence forecast (short history, stale sales) is never used as a donor or receiver of a
transfer. If it is short, the recommendation is raised with status Needs review and a person decides.
