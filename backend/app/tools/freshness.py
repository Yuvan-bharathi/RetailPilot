"""FreshnessTools — FEFO expiry risk per batch (spec §1, SD-08, D-20)."""

from collections.abc import Sequence
from datetime import date

from app.tools.numeric import floor6
from app.tools.types import BatchLike, BatchRisk


class FreshnessTools:
    @staticmethod
    def at_risk_by_batch(
        batches: Sequence[BatchLike], daily_demand: float, run_date: date
    ) -> list[BatchRisk]:
        """Quantity of each batch that will not sell before it expires, issuing earliest expiry first.

        sellable = floor(daily_demand × days_left − qty_ahead) (≥ 0) ; at_risk = max(0, qty − sellable) ;
        qty_ahead += qty − at_risk  (only units actually sold; expired units use no demand, D-31). Batches are ordered by (expiry_date, batch_id).
        """
        risks: list[BatchRisk] = []
        qty_ahead = 0
        for batch in sorted(batches, key=lambda b: (b.expiry_date, b.batch_id)):
            days_left = (batch.expiry_date - run_date).days
            sellable = max(0, floor6(daily_demand * max(days_left, 0) - qty_ahead))
            at_risk = max(0, batch.qty - sellable)
            risks.append(
                BatchRisk(
                    batch_id=batch.batch_id,
                    expiry_date=batch.expiry_date,
                    days_left=days_left,
                    qty=batch.qty,
                    sellable=sellable,
                    at_risk=at_risk,
                )
            )
            qty_ahead += batch.qty - at_risk
        return risks
