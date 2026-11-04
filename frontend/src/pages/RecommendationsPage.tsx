/** Recommendations inbox — read-only (Phase 8a). Filters live in the URL so a view can be shared or bookmarked. */
import { useDeferredValue, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { useRecommendations } from "../api/hooks";
import type { Priority, RecommendationDTO, RecStatus, RecType } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { DataTable, type Column, type TableQuery } from "../components/DataTable";
import { StatusBadge, StatusPill } from "../components/StatusBadge";
import { formatINR, formatNumber } from "../lib/format";
import { REC_TYPE_LABEL } from "../lib/labels";

const STATUSES: Array<[RecStatus, string]> = [
  ["PENDING", "Pending"],
  ["NEEDS_REVIEW", "Needs review"],
  ["ACCEPTED", "Accepted"],
  ["EDITED", "Edited"],
  ["REJECTED", "Rejected"],
  ["SUPERSEDED", "Superseded"],
];

function columns(showStore: boolean): Column<RecommendationDTO>[] {
  const all: Array<Column<RecommendationDTO> | null> = [
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
    showStore ? { id: "store", header: "Store", cell: (r) => r.store.name } : null,
    { id: "rec_type", header: "Type", sortable: true, cell: (r) => REC_TYPE_LABEL[r.rec_type] },
    { id: "qty", header: "Quantity", sortable: true, align: "right", cell: (r) => formatNumber(r.qty) },
    {
      id: "counterpart",
      header: "Other store",
      cell: (r) => (r.counterpart ? `${r.counterpart.store.name} · ${formatNumber(r.counterpart.qty)}` : "—"),
    },
    {
      id: "lost_revenue",
      header: "Lost revenue (28 days)",
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
  return all.filter((c): c is Column<RecommendationDTO> => c !== null);
}

function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T | "";
  options: Array<[T, string]>;
  onChange: (value: T | "") => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-ink-secondary">
      {label}
      <select
        className="h-10 rounded-input border border-border bg-surface px-2 text-ink"
        value={value}
        onChange={(e) => onChange(e.target.value as T | "")}
      >
        <option value="">All</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function RecommendationsPage() {
  const { user } = useAuth();
  const { storeId } = useShell();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDeferredValue(search);

  const type = (params.get("type") ?? "") as RecType | "";
  const status = (params.get("status") ?? "") as RecStatus | "";
  const priority = (params.get("priority") ?? "") as Priority | "";
  const query: TableQuery = {
    page: Number(params.get("page") ?? 1),
    pageSize: Number(params.get("size") ?? 25),
    sort: params.get("sort") ?? "-priority",
  };

  const update = (changes: Record<string, string | number | undefined>, resetPage = true) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === undefined || value === "") next.delete(key);
      else next.set(key, String(value));
    }
    if (resetPage) next.delete("page");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if ((params.get("q") ?? "") !== q) update({ q });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync the deferred search text into the URL only
  }, [q]);

  const result = useRecommendations({
    page: query.page,
    page_size: query.pageSize,
    sort: query.sort,
    q: q || undefined,
    type: type || undefined,
    status: status || undefined,
    priority: priority || undefined,
    store_id: storeId ?? undefined,
  });

  return (
    <DataTable
      caption="AI recommendations"
      columns={columns(user?.role === "SUPER_ADMIN")}
      page={result.data}
      query={query}
      onQueryChange={(next) =>
        update({ page: next.page === 1 ? undefined : next.page, size: next.pageSize === 25 ? undefined : next.pageSize, sort: next.sort }, false)
      }
      getRowId={(r) => r.rec_id}
      isLoading={result.isPending}
      isFetching={result.isFetching}
      error={result.error ? result.error.message : null}
      onRetry={() => void result.refetch()}
      onRowClick={(r) => navigate(`/recommendations/${r.rec_id}`)}
      search={{ value: search, onChange: setSearch, placeholder: "Search product, SKU or store" }}
      filters={
        <>
          <Select
            label="Type"
            value={type}
            options={(Object.keys(REC_TYPE_LABEL) as RecType[]).map((t) => [t, REC_TYPE_LABEL[t]])}
            onChange={(v) => update({ type: v })}
          />
          <Select label="Status" value={status} options={STATUSES} onChange={(v) => update({ status: v })} />
          <Select
            label="Priority"
            value={priority}
            options={[
              ["HIGH", "High"],
              ["NORMAL", "Normal"],
            ]}
            onChange={(v) => update({ priority: v })}
          />
        </>
      }
      emptyTitle="No recommendations match"
      emptyDescription="Change the search or filters."
    />
  );
}
