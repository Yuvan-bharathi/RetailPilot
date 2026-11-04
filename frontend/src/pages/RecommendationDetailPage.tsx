/** Recommendation detail — read-only (Phase 8a): explanation and evidence. Decisions arrive with Phase 6. */
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { useRecommendation } from "../api/hooks";
import { EvidenceView } from "../components/EvidencePanel";
import { ErrorState } from "../components/StateViews";
import { StatusBadge, StatusPill } from "../components/StatusBadge";
import { formatDateTimeIST, formatINR, formatNumber } from "../lib/format";
import { categoryLabel, REC_TYPE_LABEL } from "../lib/labels";

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "brand" }) {
  return (
    <div className={`rounded-card border p-3 ${tone === "brand" ? "border-brand-muted bg-brand-soft" : "border-border bg-elevated"}`}>
      <p className="text-xs text-ink-secondary">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold text-ink">{value}</p>
    </div>
  );
}

export function RecommendationDetailPage() {
  const { recId = "" } = useParams();
  const detail = useRecommendation(recId);

  const back = (
    <Link to="/recommendations" className="inline-flex items-center gap-1 text-sm text-brand hover:underline">
      <ArrowLeft aria-hidden="true" size={16} />
      All recommendations
    </Link>
  );

  if (detail.isPending) {
    return (
      <div className="space-y-4">
        {back}
        <p className="text-sm text-ink-secondary">Loading…</p>
      </div>
    );
  }
  if (detail.error || !detail.data) {
    const status = detail.error instanceof ApiError ? detail.error.status : 0;
    const message =
      status === 403
        ? "This recommendation belongs to another store."
        : status === 404
          ? "This recommendation does not exist or was superseded by a newer run."
          : (detail.error?.message ?? "Unknown error");
    return (
      <div className="space-y-4">
        {back}
        <div className="rounded-card border border-border bg-surface">
          <ErrorState message={message} onRetry={status >= 500 || status === 0 ? () => void detail.refetch() : undefined} />
        </div>
      </div>
    );
  }

  const { recommendation: rec, evidence } = detail.data;
  const transfer = evidence?.kind === "TRANSFER" ? evidence : null;
  const reorder = evidence?.kind === "REORDER" ? evidence : null;

  return (
    <div className="space-y-4">
      {back}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
        <section aria-labelledby="rec-title" className="space-y-4 rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="rec-title" className="text-lg font-semibold text-ink">
                {REC_TYPE_LABEL[rec.rec_type]} · {rec.product.name}
              </h2>
              <p className="text-sm text-ink-secondary">
                {rec.product.sku} · {categoryLabel(rec.product.category)} · {rec.store.name}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {rec.priority === "HIGH" ? <StatusBadge tone="attention" label="High priority" /> : null}
              <StatusPill status={rec.status} />
            </div>
          </div>

          {rec.explanation ? <p className="text-sm text-ink">{rec.explanation}</p> : null}

          {/* design doc §6: transfer quantity and PO remainder shown separately */}
          <div className="grid gap-3 sm:grid-cols-3">
            {transfer && !transfer.expiring_batch ? (
              <>
                <Stat label="Transfer now" value={`${formatNumber(transfer.transfer_qty)} units`} tone="brand" />
                <Stat label="Order from supplier" value={`${formatNumber(transfer.po_remainder_qty)} units`} />
              </>
            ) : reorder && reorder.transferred_qty > 0 ? (
              <>
                <Stat label="Covered by transfer" value={`${formatNumber(reorder.transferred_qty)} units`} />
                <Stat label="Order from supplier" value={`${formatNumber(rec.qty)} units`} tone="brand" />
              </>
            ) : (
              <Stat label="Recommended quantity" value={`${formatNumber(rec.qty)} units`} tone="brand" />
            )}
            {rec.lost_revenue ? <Stat label="Lost revenue (28 days)" value={formatINR(rec.lost_revenue)} /> : null}
          </div>

          {rec.counterpart ? (
            <p className="text-sm">
              {transfer?.expiring_batch ? "Batch from" : "Offered by"} <strong>{rec.counterpart.store.name}</strong> ·{" "}
              {formatNumber(rec.counterpart.qty)} units
            </p>
          ) : null}

          <p className="text-xs text-ink-secondary">
            Created {formatDateTimeIST(rec.created_at)}. Approve, edit or reject in the Approvals screen (coming in Phase 6).
          </p>
        </section>
        {evidence ? <EvidenceView evidence={evidence} /> : null}
      </div>
    </div>
  );
}
