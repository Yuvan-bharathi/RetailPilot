/**
 * Evidence behind a recommendation (design doc §6), one view per evidence `kind` of the discriminated union
 * (D-32). The switch is exhaustive: a new kind in the contract fails the type check until it has a view.
 */
import { ShieldCheck } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";

import type {
  AssortmentGapEvidence,
  BatchRiskRef,
  CoReplenishEvidence,
  Evidence,
  ExpiryEvidence,
  NeedsReviewEvidence,
  ReorderEvidence,
  TransferEvidence,
} from "../api/types";
import { formatDateIST, formatDays, formatINR, formatNumber } from "../lib/format";
import { NEED_REASON_TEXT, REVIEW_REASON_TEXT } from "../lib/labels";

/** Accessible name of the evidence landmark; unique per page when several are shown (axe landmark-unique). */
const LabelContext = createContext("Decision evidence");

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-divider py-2 last:border-b-0">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="tabular text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

function Panel({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  const label = useContext(LabelContext);
  return (
    <section aria-label={label} className="rounded-card border border-border bg-surface p-4">
      <h3 className="mb-2 text-sm font-semibold text-ink">{title}</h3>
      <dl className="text-sm">{children}</dl>
      {note ? <p className="mt-2 text-xs text-ink-secondary">{note}</p> : null}
    </section>
  );
}

const units = (n: number) => `${formatNumber(n)} units`;
const perDay = (n: number) => `${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })} / day`;

function BatchRows({ batch }: { batch: BatchRiskRef }) {
  return (
    <>
      <Row label="Batch" value={batch.batch_no} />
      <Row label="Expiry date" value={`${formatDateIST(batch.expiry_date)} (${batch.days_left} days left)`} />
      <Row label="Batch quantity" value={units(batch.batch_qty)} />
      <Row label="Will not sell in time" value={units(batch.at_risk_qty)} />
    </>
  );
}

function TransferView({ e }: { e: TransferEvidence }) {
  const scoped = e.donor !== null && e.donor_surplus == null;
  return (
    <Panel
      title={e.expiring_batch ? "Why this batch should move" : "Why this is recommended"}
      note={scoped ? "Other stores are shown by name and offered quantity only." : undefined}
    >
      {e.expiring_batch ? <BatchRows batch={e.expiring_batch} /> : <Row label="Shortage at this store" value={units(e.destination_shortage)} />}
      {e.donor ? <Row label="Offered by" value={`${e.donor.store.name} · ${units(e.donor.qty)}`} /> : null}
      {e.donor_surplus != null && !e.expiring_batch ? <Row label="Donor surplus" value={units(e.donor_surplus)} /> : null}
      {e.donor_protected_requirement != null ? (
        <Row
          label="Donor's protected requirement"
          value={
            <span className="inline-flex items-center gap-1">
              <ShieldCheck aria-hidden="true" size={14} className="text-success" />
              {units(e.donor_protected_requirement)} kept
            </span>
          }
        />
      ) : null}
      {e.donor && e.donor_protected_requirement == null && e.donor_keeps_requirement ? (
        <Row
          label="Donor protection"
          value={
            <span className="inline-flex items-center gap-1">
              <ShieldCheck aria-hidden="true" size={14} className="text-success" />
              Donor keeps its full requirement
            </span>
          }
        />
      ) : null}
      <Row label="Transfer quantity" value={units(e.transfer_qty)} />
      {!e.expiring_batch ? <Row label="Purchase order for the remainder" value={units(e.po_remainder_qty)} /> : null}
      {e.transfer_cost && e.po_incremental_cost ? (
        <Row label="Transfer cost vs extra cost of ordering" value={`${formatINR(e.transfer_cost)} vs ${formatINR(e.po_incremental_cost)}`} />
      ) : e.transfer_cost ? (
        <Row label="Transfer cost" value={formatINR(e.transfer_cost)} />
      ) : null}
      {e.expected_delivery ? <Row label="Expected delivery" value={formatDateIST(e.expected_delivery)} /> : null}
      <Row label="Days of cover" value={`${formatDays(e.days_of_cover_before)} → ${formatDays(e.days_of_cover_after)}`} />
    </Panel>
  );
}

function ReorderView({ e }: { e: ReorderEvidence }) {
  return (
    <Panel title="Why order from the supplier">
      <Row label="Reason" value={NEED_REASON_TEXT[e.reason]} />
      <Row label="Forecast demand" value={perDay(e.daily_demand)} />
      <Row
        label="Days covered until next delivery"
        value={`${e.lead_time_days} lead + ${e.review_period_days} review + ${e.safety_stock_days} safety`}
      />
      <Row label="Display minimum" value={units(e.min_display_qty)} />
      <Row label="Own requirement" value={units(e.own_requirement)} />
      <Row label="Available (shelf + backroom + incoming − reserved)" value={units(e.available)} />
      <Row label="Need" value={units(e.need_qty)} />
      {e.transferred_qty > 0 ? <Row label="Covered by transfers" value={units(e.transferred_qty)} /> : null}
      <Row label="Days of cover now" value={formatDays(e.days_of_cover)} />
      <Row label="Supplier" value={e.supplier.name} />
      {e.lost_revenue ? <Row label="Lost revenue (last 28 days)" value={formatINR(e.lost_revenue)} /> : null}
      {e.lost_profit ? <Row label="Lost profit (last 28 days)" value={formatINR(e.lost_profit)} /> : null}
    </Panel>
  );
}

function CoReplenishView({ e }: { e: CoReplenishEvidence }) {
  return (
    <Panel title="Why add this to the order">
      <Row label="Bought together with" value={e.linked_product.name} />
      <Row label="Lift" value={e.lift.toFixed(2)} />
      <Row label="Confidence" value={`${(e.confidence * 100).toFixed(1)}%`} />
      <Row label="Support" value={`${(e.support * 100).toFixed(2)}% of bills`} />
      <Row label="Forecast demand" value={perDay(e.daily_demand)} />
      <Row label="Available now" value={units(e.available)} />
      <Row label={`Expected at next review (${e.review_period_days} days)`} value={units(Math.round(e.projected_at_next_review))} />
      <Row label="Own requirement" value={units(e.own_requirement)} />
      <Row label="Same delivery as" value={e.supplier.name} />
    </Panel>
  );
}

function ExpiryView({ e }: { e: ExpiryEvidence }) {
  return (
    <Panel title="Why this is an expiry alert">
      <BatchRows batch={e.batch} />
      <Row label="Forecast demand here" value={perDay(e.daily_demand)} />
      <Row label="Other stores checked" value={`${e.receivers_checked} (none can sell it in time)`} />
      {e.markdown_pct != null ? <Row label="Suggested markdown" value={`${e.markdown_pct}%`} /> : null}
    </Panel>
  );
}

function GapView({ e }: { e: AssortmentGapEvidence }) {
  return (
    <Panel title="Why list this product">
      <Row label="Sells together with" value={e.antecedent.name} />
      <Row label="Lift" value={e.lift.toFixed(2)} />
      <Row label="Seen in" value={e.source_stores.map((s) => s.name).join(", ")} />
    </Panel>
  );
}

function NeedsReviewView({ e }: { e: NeedsReviewEvidence }) {
  return (
    <Panel title="Why this needs your review">
      <Row label="Reason" value={REVIEW_REASON_TEXT[e.reason]} />
      <Row label="Own requirement" value={units(e.own_requirement)} />
      <Row label="Available" value={units(e.available)} />
      <Row label="Suggested quantity" value={units(e.suggested_qty)} />
      <Row label="Detail" value={e.detail} />
    </Panel>
  );
}

export function EvidenceView({ evidence, label }: { evidence: Evidence; label?: string }) {
  const view = renderEvidence(evidence);
  return label ? <LabelContext.Provider value={label}>{view}</LabelContext.Provider> : view;
}

function renderEvidence(evidence: Evidence) {
  switch (evidence.kind) {
    case "TRANSFER":
      return <TransferView e={evidence} />;
    case "REORDER":
      return <ReorderView e={evidence} />;
    case "CO_REPLENISH":
      return <CoReplenishView e={evidence} />;
    case "EXPIRY":
      return <ExpiryView e={evidence} />;
    case "ASSORTMENT_GAP":
      return <GapView e={evidence} />;
    case "NEEDS_REVIEW":
      return <NeedsReviewView e={evidence} />;
    default: {
      const unhandled: never = evidence;
      return unhandled;
    }
  }
}
