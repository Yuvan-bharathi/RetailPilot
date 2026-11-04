import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import type { TransferEvidenceDTO } from "../api/types";
import { formatDateIST, formatDays, formatINR, formatNumber } from "../lib/format";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-divider py-2 last:border-b-0">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="tabular text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

/**
 * Evidence behind a transfer / PO-remainder recommendation (design doc §6). Donor stock details are shown only
 * when the API sends them (Super Admin); a Store Supervisor sees the other store as name + offered quantity.
 */
export function EvidencePanel({ evidence }: { evidence: TransferEvidenceDTO }) {
  const scoped = evidence.donor !== null && evidence.donor_surplus === null;
  return (
    <section aria-label="Decision evidence" className="rounded-card border border-border bg-surface p-4">
      <h3 className="mb-2 text-sm font-semibold text-ink">Why this is recommended</h3>
      <dl className="text-sm">
        <Row label="Shortage at this store" value={`${formatNumber(evidence.destination_shortage)} units`} />
        {evidence.donor ? (
          <Row label="Offered by" value={`${evidence.donor.store.name} · ${formatNumber(evidence.donor.qty)} units`} />
        ) : null}
        {evidence.donor_surplus !== null && evidence.donor_surplus !== undefined ? (
          <Row label="Donor surplus" value={`${formatNumber(evidence.donor_surplus)} units`} />
        ) : null}
        {evidence.donor_protected_requirement !== null && evidence.donor_protected_requirement !== undefined ? (
          <Row
            label="Donor's protected requirement"
            value={
              <span className="inline-flex items-center gap-1">
                <ShieldCheck aria-hidden="true" size={14} className="text-success" />
                {formatNumber(evidence.donor_protected_requirement)} units kept
              </span>
            }
          />
        ) : null}
        <Row label="Transfer quantity" value={`${formatNumber(evidence.transfer_qty)} units`} />
        <Row label="Purchase order for the remainder" value={`${formatNumber(evidence.po_remainder_qty)} units`} />
        {evidence.transfer_cost && evidence.po_incremental_cost ? (
          <Row
            label="Transfer cost vs extra cost of ordering"
            value={`${formatINR(evidence.transfer_cost)} vs ${formatINR(evidence.po_incremental_cost)}`}
          />
        ) : null}
        {evidence.expected_delivery ? <Row label="Expected delivery" value={formatDateIST(evidence.expected_delivery)} /> : null}
        <Row
          label="Days of cover"
          value={`${formatDays(evidence.days_of_cover_before)} → ${formatDays(evidence.days_of_cover_after)}`}
        />
      </dl>
      {scoped ? (
        <p className="mt-2 text-xs text-ink-secondary">
          Other stores are shown by name and offered quantity only.
        </p>
      ) : null}
    </section>
  );
}
