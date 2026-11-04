/** Design-system demo page (/components): every shared component and state, wired to the mock API. */
import { Check, Download, Trash2 } from "lucide-react";
import { useDeferredValue, useState, type ReactNode } from "react";

import { useDashboard, useRecommendations } from "../api/hooks";
import type { RecommendationDTO, RecStatus } from "../api/types";
import { useShell } from "../app/ShellContext";
import { Button } from "../components/Button";
import { DataTable, type Column, type TableQuery } from "../components/DataTable";
import { DeadlineCountdown } from "../components/DeadlineCountdown";
import { EvidenceView } from "../components/EvidencePanel";
import { KpiCard } from "../components/KpiCard";
import { ConfirmDialog, Modal } from "../components/Modal";
import { StatusBadge, StatusPill } from "../components/StatusBadge";
import { Stepper, TRANSFER_STEPS } from "../components/Stepper";
import { formatINR, formatINRCompact, formatNumber, formatPercent } from "../lib/format";
import { REC_TYPE_LABEL } from "../lib/labels";
import { EXAMPLE_EVIDENCE } from "../mocks/examples";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`sec-${title}`} className="space-y-3">
      <h2 id={`sec-${title}`} className="text-lg font-semibold text-ink">
        {title}
      </h2>
      {children}
    </section>
  );
}

const REC_COLUMNS: Column<RecommendationDTO>[] = [
  {
    id: "name",
    header: "Product",
    sortable: true,
    hideable: false,
    cell: (r) => (
      <span>
        <span className="font-medium text-ink">{r.product.name}</span>
        <span className="block text-xs text-ink-secondary">{r.product.sku}</span>
      </span>
    ),
  },
  { id: "store", header: "Store", cell: (r) => r.store.name },
  { id: "rec_type", header: "Type", sortable: true, cell: (r) => REC_TYPE_LABEL[r.rec_type] },
  { id: "qty", header: "Qty", sortable: true, align: "right", cell: (r) => formatNumber(r.qty) },
  {
    id: "counterpart",
    header: "Other store",
    cell: (r) => (r.counterpart ? `${r.counterpart.store.name} · ${formatNumber(r.counterpart.qty)}` : "—"),
  },
  {
    id: "lost_revenue",
    header: "Lost revenue",
    sortable: true,
    align: "right",
    cell: (r) => (r.lost_revenue ? formatINR(r.lost_revenue) : "—"),
  },
  {
    id: "priority",
    header: "Priority",
    sortable: true,
    cell: (r) =>
      r.priority === "HIGH" ? <StatusBadge tone="attention" label="High" /> : <StatusBadge tone="neutral" label="Normal" />,
  },
  { id: "status", header: "Status", sortable: true, cell: (r) => <StatusPill status={r.status} /> },
];

const STATUS_FILTERS: Array<{ value: "" | RecStatus; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "PENDING", label: "Pending" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
  { value: "ACCEPTED", label: "Accepted" },
  { value: "REJECTED", label: "Rejected" },
];

function RecommendationsTable() {
  const { storeId } = useShell();
  const [query, setQuery] = useState<TableQuery>({ page: 1, pageSize: 10, sort: "-priority" });
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"" | RecStatus>("");
  const [selection, setSelection] = useState<Record<string, true>>({});
  const q = useDeferredValue(search);
  const result = useRecommendations({
    page: query.page,
    page_size: query.pageSize,
    sort: query.sort,
    q: q || undefined,
    status: status || undefined,
    store_id: storeId ?? undefined,
  });
  const selected = Object.values(selection).filter(Boolean).length;

  return (
    <DataTable
      caption="AI recommendations"
      columns={REC_COLUMNS}
      page={result.data}
      query={query}
      onQueryChange={setQuery}
      getRowId={(r) => r.rec_id}
      isLoading={result.isPending}
      isFetching={result.isFetching}
      error={result.error ? result.error.message : null}
      onRetry={() => void result.refetch()}
      search={{
        value: search,
        onChange: (v) => {
          setSearch(v);
          setQuery((prev) => ({ ...prev, page: 1 }));
        },
        placeholder: "Search product, SKU or store",
      }}
      filters={
        <>
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            Status
            <select
              className="h-10 rounded-input border border-border bg-surface px-2 text-ink"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as "" | RecStatus);
                setQuery((prev) => ({ ...prev, page: 1 }));
              }}
            >
              {STATUS_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          {selected > 0 ? <span className="text-sm text-ink-secondary">{selected} selected</span> : null}
        </>
      }
      selection={{ value: selection, onChange: setSelection }}
      emptyTitle="No recommendations match"
      emptyDescription="Change the search or status filter."
    />
  );
}

const EVIDENCE_EXAMPLES: Array<[string, keyof typeof EXAMPLE_EVIDENCE]> = [
  ["Transfer — Super Admin / donor store view", "TRANSFER"],
  ["Transfer — destination store view (D-32)", "TRANSFER_DESTINATION"],
  ["Reorder", "REORDER"],
  ["Co-replenish", "CO_REPLENISH"],
  ["Expiry alert", "EXPIRY"],
  ["Assortment gap", "ASSORTMENT_GAP"],
  ["Needs review", "NEEDS_REVIEW"],
];

function EvidenceExamples() {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      {EVIDENCE_EXAMPLES.map(([title, key]) => (
        <div key={key} className="space-y-2">
          <p className="text-sm font-medium text-ink-secondary">{title}</p>
          <EvidenceView evidence={EXAMPLE_EVIDENCE[key]} label={`Evidence example: ${title}`} />
        </div>
      ))}
    </div>
  )
}

export function ComponentsPage() {
  const { storeId, period } = useShell();
  const dashboard = useDashboard({ store_id: storeId ?? undefined, period });
  const [now] = useState(() => Date.now());
  const [modalOpen, setModalOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const hours = (h: number) => new Date(now + h * 3_600_000).toISOString();

  return (
    <div className="space-y-8">
      <p className="text-sm text-ink-secondary">
        Shared components for both roles (docs/03-design-system.md). Data comes from the mock API behind the generated
        OpenAPI types.
      </p>

      <Section title="KPI cards">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {dashboard.data ? (
            <>
              <KpiCard
                title="Revenue"
                value={formatINRCompact(dashboard.data.revenue)}
                trend={{ direction: "up", label: "+4.2% vs previous", tone: "success" }}
                meta={`Gross profit ${formatINRCompact(dashboard.data.gross_profit)}`}
              />
              <KpiCard
                title="Lost revenue"
                value={formatINRCompact(dashboard.data.lost_revenue)}
                trend={{ direction: "down", label: "−8% vs previous", tone: "success" }}
                meta="Sales missed during stockouts"
              />
              <KpiCard
                title="Lost profit"
                value={formatINRCompact(dashboard.data.lost_profit)}
                meta="Margin on the missed sales"
              />
              <KpiCard
                title="Stockout rate"
                value={formatPercent(dashboard.data.stockout_rate)}
                trend={{ direction: "up", label: "+0.6 pts", tone: "danger" }}
                meta={`${dashboard.data.pending_recommendations} recommendations pending`}
              />
            </>
          ) : (
            <p className="text-sm text-ink-secondary">Loading KPIs…</p>
          )}
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap gap-3">
          <Button icon={<Check size={16} />}>Approve</Button>
          <Button variant="secondary" icon={<Download size={16} />}>
            Export
          </Button>
          <Button variant="tertiary">View evidence</Button>
          <Button variant="destructive" icon={<Trash2 size={16} />}>
            Reject
          </Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      <Section title="Status badges">
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone="success" label="Approved" />
          <StatusBadge tone="warning" label="Needs review" />
          <StatusBadge tone="attention" label="Escalated" />
          <StatusBadge tone="danger" label="Rejected" />
          <StatusBadge tone="info" label="Pending L1" />
          <StatusBadge tone="neutral" label="Superseded" />
        </div>
      </Section>

      <Section title="Data table (server-side paging)">
        <RecommendationsTable />
      </Section>

      <Section title="Table states">
        <div className="grid gap-4 lg:grid-cols-3">
          {(["loading", "empty", "error"] as const).map((state) => (
            <DataTable<RecommendationDTO>
              key={state}
              caption={`Example: ${state}`}
              columns={REC_COLUMNS.slice(0, 3)}
              page={state === "empty" ? { items: [], total: 0, page: 1, page_size: 10 } : undefined}
              query={{ page: 1, pageSize: 10 }}
              onQueryChange={() => undefined}
              getRowId={(r) => r.rec_id}
              isLoading={state === "loading"}
              error={state === "error" ? "The server did not respond." : null}
              onRetry={() => undefined}
              emptyTitle="No recommendations"
            />
          ))}
        </div>
      </Section>

      <Section title="Evidence views (one per kind)">
        <EvidenceExamples />
      </Section>

      <Section title="Transfer stepper">
        <div className="space-y-6 rounded-card border border-border bg-surface p-4">
          <Stepper label="Transfer in progress" steps={TRANSFER_STEPS} current="DONOR_APPROVED" />
          <Stepper label="Transfer rejected" steps={TRANSFER_STEPS} current="DEST_ACCEPTED" failed={{ label: "Rejected by donor" }} />
          <Stepper
            label="Transfer received"
            steps={TRANSFER_STEPS}
            current="RECEIVED"
            note="Discrepancy: 12 sent, 11 received (₹42 transit loss)."
          />
        </div>
      </Section>

      <Section title="Approval deadline">
        <div className="flex flex-wrap gap-3">
          <DeadlineCountdown deadline={hours(5.5)} now={now} />
          <DeadlineCountdown deadline={hours(1.25)} now={now} />
          <DeadlineCountdown deadline={hours(-2.2)} now={now} />
          <DeadlineCountdown deadline={hours(-3)} escalated now={now} />
        </div>
      </Section>

      <Section title="Modals">
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => setModalOpen(true)}>
            Open modal
          </Button>
          <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
            Reject PO line…
          </Button>
          {lastAction ? <span className="self-center text-sm text-ink-secondary" role="status">{lastAction}</span> : null}
        </div>
        <Modal
          open={modalOpen}
          title="Edit quantity"
          description="Change the quantity for your store's line."
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button onClick={() => setModalOpen(false)}>Save</Button>
            </>
          }
        >
          <label htmlFor="demo-qty" className="text-sm font-medium">
            Quantity
          </label>
          <input id="demo-qty" type="number" defaultValue={36} className="mt-1 h-10 w-full rounded-input border border-border px-3" />
        </Modal>
        <ConfirmDialog
          open={confirmOpen}
          title="Reject this PO line?"
          reason="Store B does not need Rice 5 kg this week."
          consequences={[
            "The line is closed with your reason recorded.",
            "Other stores' approved lines continue as a split PO.",
            "The need is recalculated in tonight's run.",
          ]}
          approver="Your decision is final for your store's line (L1)."
          confirmLabel="Reject line"
          destructive
          requireReason
          onCancel={() => setConfirmOpen(false)}
          onConfirm={(why) => {
            setConfirmOpen(false);
            setLastAction(`Rejected with reason: ${why ?? ""}`);
          }}
        />
      </Section>
    </div>
  );
}
