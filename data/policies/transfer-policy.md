# Stock Transfer Policy

## Donor protection
A transfer never takes the donor store below its own requirement. Before dispatch the system re-checks the donor's
surplus; if it has fallen, the transfer cannot be dispatched.

## Approval steps
1. The destination store's supervisor accepts the proposed transfer.
2. The donor store's supervisor approves the release.
3. The system re-checks the donor's surplus.
4. The donor dispatches the goods.
5. The receiving supervisor confirms the quantity received; any difference is recorded as a discrepancy on the
   transfer.

## Reservations while in flight
When the destination accepts, the quantity counts as incoming for the receiver and as reserved for the donor. Both
are released if the transfer is rejected or cancelled.

## Cancelled and rejected transfers
A cancelled transfer is not carried forward. The next nightly run recalculates the need from the current position.

## Receiving a transfer
The receiving supervisor counts the goods and confirms the received quantity in Stock transfers. Stock changes only
through the inventory ledger: the receipt creates TRANSFER_IN and TRANSFER_OUT movements. A difference between sent
and received quantity is recorded with its value on the transfer.

## Store visibility
A store supervisor sees only their own store's stock. In a transfer they see the other store's name and the
offered quantity, never its stock levels.
