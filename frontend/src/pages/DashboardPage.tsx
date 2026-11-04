/**
 * Overview dashboards (Super Admin: all stores or one store; Store Supervisor: own store) — D-46.
 * Every figure comes from GET /dashboard and GET /dashboard/insights; a widget without data shows an empty state,
 * never sample numbers. The role and store come from the signed-in user and the header's store/period pickers.
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useDashboard, useDashboardInsights, useRecommendations } from "../api/hooks";
import type { DashboardInsights, DashboardSummary } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { KpiCard } from "../components/KpiCard";
import { EmptyState, ErrorState, SkeletonLine } from "../components/StateViews";
import { formatDateIST, formatINR, formatINRCompact, formatNumber, formatPercent } from "../lib/format";
import { categoryLabel, REC_TYPE_LABEL } from "../lib/labels";

const SERIES_COLOURS = [
  "var(--brand-primary)",
  "var(--accent-lavender)",
  "var(--accent-sage)",
  "var(--accent-sand)",
  "var(--accent-blue)",
  "var(--accent-stone)",
];
const AXIS_TICK = { fontSize: 11, fill: "var(--text-secondary)" };
const TOOLTIP_STYLE = {
  backgroundColor: "var(--surface)",
  borderColor: "var(--border)",
  borderRadius: "8px",
  fontSize: "12px",
};

function Card({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`rounded-card border border-border bg-surface p-5 shadow-card ${className}`}>
      <h2 className="border-b border-divider pb-3 text-sm font-semibold text-ink">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Loading / error / empty handling shared by every widget. */
function Widget({
  loading,
  error,
  empty,
  emptyTitle,
  children,
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyTitle: string;
  children: ReactNode;
}) {
  if (loading)
    return (
      <div className="space-y-3 py-2">
        <SkeletonLine />
        <SkeletonLine width="80%" />
        <SkeletonLine width="60%" />
      </div>
    );
  if (error) return <ErrorState message={error} />;
  if (empty) return <EmptyState title={emptyTitle} description="Shown after the nightly run has data for it." />;
  return <>{children}</>;
}

function shortDay(iso: string): string {
  return formatDateIST(iso).replace(/\s\d{4}$/, "");
}

// --- widgets ---------------------------------------------------------------------------------------------------------

function KpiRow({ summary, insights }: { summary: DashboardSummary; insights: DashboardInsights | undefined }) {
  const risk = insights?.stock_health;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        title="Revenue"
        value={formatINRCompact(summary.revenue)}
        meta={`Gross margin ${summary.margin_pct.toFixed(1)}%`}
      />
      <KpiCard
        title="Stock availability"
        value={formatPercent(1 - summary.stockout_rate)}
        meta="Share of tracked products in stock"
      />
      <KpiCard
        title="Lost revenue"
        value={formatINRCompact(summary.lost_revenue)}
        meta={`Lost profit ${formatINRCompact(summary.lost_profit)}`}
      />
      <KpiCard title="Inventory value" value={formatINRCompact(summary.inventory_value)} meta="At cost" />
      <KpiCard
        title="High stock-out risk"
        value={risk ? formatNumber(risk.high_risk) : "—"}
        meta={risk ? `${formatNumber(risk.out_of_stock)} out of stock` : undefined}
      />
      <KpiCard
        title="Near-expiry value"
        value={formatINRCompact(summary.near_expiry_value)}
        meta="Expiring within 14 days"
      />
      <KpiCard title="Pending recommendations" value={formatNumber(summary.pending_recommendations)} />
      <KpiCard
        title="Active transfers"
        value={formatNumber(summary.active_transfers)}
        meta={`${formatNumber(summary.pending_purchase_orders)} PO lines awaiting approval`}
      />
    </div>
  );
}

function SalesTrend({ insights }: { insights: DashboardInsights }) {
  const forecast = insights.forecast_units_per_day;
  return (
    <>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={insights.sales_trend} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis dataKey="day" tickFormatter={shortDay} tick={AXIS_TICK} axisLine={false} tickLine={false} />
            <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={48} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(d) => formatDateIST(String(d))}
              formatter={(v) => [formatNumber(Number(v)), "Units sold"]}
            />
            <Line type="monotone" dataKey="units" stroke="var(--brand-primary)" strokeWidth={2} dot={false} />
            {forecast !== null ? (
              <ReferenceLine y={forecast} stroke="var(--accent-lavender)" strokeDasharray="4 4" strokeWidth={2} />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-ink-secondary">
        Units sold per day
        {forecast !== null ? ` · dashed line: forecast demand ${formatNumber(Math.round(forecast))} units/day` : ""}
      </p>
    </>
  );
}

function CategoryDonut({ insights }: { insights: DashboardInsights }) {
  const data = insights.inventory_by_category.map((c, i) => ({
    name: categoryLabel(c.category),
    value: Number(c.value),
    fill: SERIES_COLOURS[i % SERIES_COLOURS.length],
  }));
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
      <div className="h-48 w-full sm:w-1/2">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" paddingAngle={1} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => formatINR(Number(v), { whole: true })} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="w-full space-y-1.5 text-sm sm:w-1/2">
        {data.map((entry) => (
          <li key={entry.name} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-ink-secondary">
              <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: entry.fill }} />
              {entry.name}
            </span>
            <span className="tabular font-medium text-ink">{formatINRCompact(entry.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StockHealth({ insights }: { insights: DashboardInsights }) {
  const h = insights.stock_health;
  const total = h.high_risk + h.medium_risk + h.low_risk;
  const parts = [
    { label: "High risk", value: h.high_risk, colour: "var(--danger-text)" },
    { label: "Medium risk", value: h.medium_risk, colour: "var(--warning-text)" },
    { label: "Low risk", value: h.low_risk, colour: "var(--success-text)" },
  ];
  const shelf = Number(insights.shelf_value);
  const backroom = Number(insights.backroom_value);
  return (
    <>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-elevated" aria-hidden="true">
        {parts.map((p) => (
          <div key={p.label} style={{ width: `${total ? (p.value / total) * 100 : 0}%`, backgroundColor: p.colour }} />
        ))}
      </div>
      <ul className="mt-3 space-y-1.5 text-sm">
        {parts.map((p) => (
          <li key={p.label} className="flex justify-between">
            <span className="text-ink-secondary">{p.label}</span>
            <span className="tabular font-medium text-ink">
              {formatNumber(p.value)} ({total ? formatPercent(p.value / total) : "—"})
            </span>
          </li>
        ))}
        <li className="flex justify-between">
          <span className="text-ink-secondary">Out of stock</span>
          <span className="tabular font-medium text-ink">{formatNumber(h.out_of_stock)}</span>
        </li>
      </ul>
      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-divider pt-3 text-sm">
        <div>
          <dt className="text-ink-secondary">Shelf stock</dt>
          <dd className="tabular font-semibold text-ink">
            {formatINRCompact(shelf)} {shelf + backroom ? `(${formatPercent(shelf / (shelf + backroom))})` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-ink-secondary">Backroom stock</dt>
          <dd className="tabular font-semibold text-ink">
            {formatINRCompact(backroom)} {shelf + backroom ? `(${formatPercent(backroom / (shelf + backroom))})` : ""}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-ink-secondary">
        Risk: days of cover below the supplier lead time (high) or lead time + review period (medium).
      </p>
    </>
  );
}

function ExpiryChart({ insights }: { insights: DashboardInsights }) {
  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={insights.expiry_next_14_days} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
          <XAxis dataKey="day" tickFormatter={shortDay} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={40} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(d) => formatDateIST(String(d))}
            formatter={(v) => [formatNumber(Number(v)), "Units expiring"]}
          />
          <Bar dataKey="qty" fill="var(--warning-text)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function PoStatus({ insights }: { insights: DashboardInsights }) {
  const max = Math.max(...insights.po_status.map((p) => p.count), 1);
  return (
    <ul className="space-y-3 text-sm">
      {insights.po_status.map((p) => (
        <li key={p.status}>
          <div className="flex justify-between">
            <span className="text-ink-secondary">{p.status.replaceAll("_", " ").toLowerCase()}</span>
            <span className="tabular font-medium text-ink">
              {formatNumber(p.count)} · {formatINRCompact(p.value)}
            </span>
          </div>
          <div className="mt-1 h-2 w-full rounded-full bg-elevated" aria-hidden="true">
            <div className="h-2 rounded-full bg-brand" style={{ width: `${(p.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function StorePerformance({ insights }: { insights: DashboardInsights }) {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Store performance</caption>
      <thead>
        <tr className="text-left text-xs text-ink-secondary">
          <th scope="col" className="pb-2 font-medium">
            Store
          </th>
          <th scope="col" className="pb-2 text-right font-medium">
            Revenue
          </th>
          <th scope="col" className="pb-2 text-right font-medium">
            Availability
          </th>
          <th scope="col" className="pb-2 text-right font-medium">
            High-risk SKUs
          </th>
        </tr>
      </thead>
      <tbody>
        {insights.store_performance.map((s) => (
          <tr key={s.store.store_id} className="border-t border-divider">
            <td className="py-2 text-ink">{s.store.name}</td>
            <td className="tabular py-2 text-right">{formatINRCompact(s.revenue)}</td>
            <td className="tabular py-2 text-right">{formatPercent(1 - s.stockout_rate)}</td>
            <td className="tabular py-2 text-right">{formatNumber(s.high_risk_skus)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Movers({ summary }: { summary: DashboardSummary }) {
  const list = (title: string, items: DashboardSummary["fast_movers"]) => (
    <div>
      <h3 className="mb-2 text-xs font-medium text-ink-secondary">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-ink-secondary">No sales in this period.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {items.map((m) => (
            <li key={m.product.product_id} className="flex justify-between gap-2">
              <span className="truncate text-ink">{m.product.name}</span>
              <span className="tabular shrink-0 text-ink-secondary">{formatNumber(m.units)} units</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {list("Fast movers", summary.fast_movers)}
      {list("Slow movers", summary.slow_movers)}
    </div>
  );
}

function TopRecommendations({ storeId }: { storeId: string | null }) {
  const recs = useRecommendations({
    status: "PENDING",
    sort: "-priority",
    page_size: 5,
    store_id: storeId ?? undefined,
  });
  return (
    <Widget
      loading={recs.isPending}
      error={recs.error ? recs.error.message : null}
      empty={(recs.data?.items.length ?? 0) === 0}
      emptyTitle="No pending recommendations"
    >
      <ul className="space-y-3 text-sm">
        {recs.data?.items.map((r) => (
          <li key={r.rec_id} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Link to={`/recommendations/${r.rec_id}`} className="font-medium text-ink hover:underline">
                {REC_TYPE_LABEL[r.rec_type]} · {r.product.name}
              </Link>
              <p className="truncate text-xs text-ink-secondary">
                {r.store.name}
                {r.priority === "HIGH" ? " · High priority" : ""}
              </p>
            </div>
            <span className="tabular shrink-0 font-medium text-ink">{formatNumber(r.qty)} units</span>
          </li>
        ))}
      </ul>
      <Link to="/recommendations" className="mt-4 inline-block text-sm font-medium text-brand hover:underline">
        Open recommendations
      </Link>
    </Widget>
  );
}

// --- page ------------------------------------------------------------------------------------------------------------

export function DashboardPage() {
  const { user } = useAuth();
  const { storeId, period } = useShell();
  const isAdmin = user?.role === "SUPER_ADMIN";
  const scope = isAdmin ? storeId : (user?.store?.store_id ?? null);
  const query = { store_id: scope ?? undefined, period };
  const summary = useDashboard(query);
  const insights = useDashboardInsights(query);

  const ins = insights.data;
  const insightsState = {
    loading: insights.isPending,
    error: insights.error ? insights.error.message : null,
  };
  const scopeName = summary.data?.store?.name ?? (isAdmin && scope === null ? "All stores" : user?.store?.name);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-ink">
          {isAdmin ? "Business Overview" : "Store Dashboard"}
        </h1>
        <p className="mt-1 text-sm text-ink-secondary">
          {scopeName ?? ""}
          {ins?.data_as_of ? ` · Data as of ${formatDateIST(ins.data_as_of)}` : ""}
        </p>
      </header>

      {summary.isPending ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="rounded-card border border-border bg-surface p-4 shadow-card">
              <SkeletonLine width="50%" />
              <div className="mt-3">
                <SkeletonLine width="70%" />
              </div>
            </div>
          ))}
        </div>
      ) : summary.error ? (
        <ErrorState message={summary.error.message} onRetry={() => void summary.refetch()} />
      ) : summary.data ? (
        <KpiRow summary={summary.data} insights={ins} />
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <Card title="Sales vs. forecast demand" className="lg:col-span-7">
          <Widget {...insightsState} empty={!ins?.sales_trend.length} emptyTitle="No sales in this period">
            {ins ? <SalesTrend insights={ins} /> : null}
          </Widget>
        </Card>
        <Card title="Inventory by category (at cost)" className="lg:col-span-5">
          <Widget {...insightsState} empty={!ins?.inventory_by_category.length} emptyTitle="No stock on hand">
            {ins ? <CategoryDonut insights={ins} /> : null}
          </Widget>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <Card title="Stock health" className="lg:col-span-4">
          <Widget
            {...insightsState}
            empty={!ins || ins.stock_health.high_risk + ins.stock_health.medium_risk + ins.stock_health.low_risk === 0}
            emptyTitle="No listed products"
          >
            {ins ? <StockHealth insights={ins} /> : null}
          </Widget>
        </Card>
        <Card title="Expiry risk (next 14 days)" className="lg:col-span-4">
          <Widget {...insightsState} empty={!ins?.expiry_next_14_days.length} emptyTitle="Nothing expires in 14 days">
            {ins ? <ExpiryChart insights={ins} /> : null}
          </Widget>
        </Card>
        <Card title="Purchase orders by status" className="lg:col-span-4">
          <Widget {...insightsState} empty={!ins?.po_status.length} emptyTitle="No purchase orders">
            {ins ? <PoStatus insights={ins} /> : null}
          </Widget>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {isAdmin && scope === null ? (
          <Card title="Store performance" className="lg:col-span-5">
            <Widget {...insightsState} empty={!ins?.store_performance.length} emptyTitle="No stores">
              {ins ? <StorePerformance insights={ins} /> : null}
            </Widget>
          </Card>
        ) : (
          <Card title="Fast and slow movers" className="lg:col-span-5">
            {summary.data ? <Movers summary={summary.data} /> : <SkeletonLine />}
          </Card>
        )}
        <Card title="Pending recommendations (highest priority first)" className="lg:col-span-7">
          <TopRecommendations storeId={scope} />
        </Card>
      </div>
    </div>
  );
}
