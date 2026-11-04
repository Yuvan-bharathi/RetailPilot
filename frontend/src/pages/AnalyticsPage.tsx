/**
 * Analytics (D-48): ABC-XYZ classification, category performance, forecast method mix and top lost sales.
 * Every figure comes from GET /analytics; sections without data show an empty state, never sample numbers.
 */
import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useAnalytics } from "../api/hooks";
import type { AnalyticsDTO } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { EmptyState, ErrorState, SkeletonLine } from "../components/StateViews";
import { formatDateIST, formatINR, formatINRCompact, formatNumber } from "../lib/format";
import { categoryLabel } from "../lib/labels";

const ABC = ["A", "B", "C"] as const;
const XYZ = ["X", "Y", "Z"] as const;
const AXIS_TICK = { fontSize: 11, fill: "var(--text-secondary)" };

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="rounded-card border border-border bg-surface p-5 shadow-card">
      <h2 className="border-b border-divider pb-3 text-sm font-semibold text-ink">{title}</h2>
      <div className="mt-4">{children}</div>
      {note ? <p className="mt-3 text-xs text-ink-secondary">{note}</p> : null}
    </section>
  );
}

function AbcXyz({ data }: { data: AnalyticsDTO }) {
  const cell = (a: string, x: string) => data.abc_xyz.find((c) => c.abc === a && c.xyz === x)?.skus ?? 0;
  const max = Math.max(...data.abc_xyz.map((c) => c.skus), 1);
  return (
    <table className="w-full text-center text-sm">
      <caption className="sr-only">Store-SKUs by ABC (value) and XYZ (demand variability) class</caption>
      <thead>
        <tr className="text-xs text-ink-secondary">
          <th scope="col" className="pb-2">
            <span className="sr-only">ABC class</span>
          </th>
          {XYZ.map((x) => (
            <th key={x} scope="col" className="pb-2 font-medium">
              {x} {x === "X" ? "(steady)" : x === "Y" ? "(variable)" : "(erratic)"}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ABC.map((a) => (
          <tr key={a}>
            <th scope="row" className="py-1 pr-2 text-left text-xs font-medium text-ink-secondary">
              {a} {a === "A" ? "(top value)" : a === "B" ? "(middle)" : "(tail)"}
            </th>
            {XYZ.map((x) => {
              const n = cell(a, x);
              return (
                <td key={x} className="p-1">
                  <div
                    className="tabular rounded-input border border-border py-3 font-semibold text-ink"
                    style={{
                      backgroundColor: `color-mix(in srgb, var(--brand-primary) ${Math.round((n / max) * 30)}%, var(--surface))`,
                    }}
                  >
                    {formatNumber(n)}
                  </div>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Categories({ data }: { data: AnalyticsDTO }) {
  const chart = data.categories.map((c) => ({ name: categoryLabel(c.category), revenue: Number(c.revenue) }));
  return (
    <>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
            <XAxis dataKey="name" tick={AXIS_TICK} axisLine={false} tickLine={false} />
            <YAxis
              tick={AXIS_TICK}
              axisLine={false}
              tickLine={false}
              width={56}
              tickFormatter={(v) => formatINRCompact(v)}
            />
            <Tooltip formatter={(v) => [formatINR(Number(v), { whole: true }), "Revenue"]} />
            <Bar dataKey="revenue" fill="var(--brand-primary)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-4 w-full text-sm">
        <caption className="sr-only">Revenue and margin by category</caption>
        <thead>
          <tr className="text-left text-xs text-ink-secondary">
            <th scope="col" className="pb-2 font-medium">
              Category
            </th>
            <th scope="col" className="pb-2 text-right font-medium">
              Revenue
            </th>
            <th scope="col" className="pb-2 text-right font-medium">
              Gross profit
            </th>
            <th scope="col" className="pb-2 text-right font-medium">
              Margin
            </th>
            <th scope="col" className="pb-2 text-right font-medium">
              Units
            </th>
          </tr>
        </thead>
        <tbody>
          {data.categories.map((c) => (
            <tr key={c.category} className="border-t border-divider">
              <td className="py-2 text-ink">{categoryLabel(c.category)}</td>
              <td className="tabular py-2 text-right">{formatINRCompact(c.revenue)}</td>
              <td className="tabular py-2 text-right">{formatINRCompact(c.gross_profit)}</td>
              <td className="tabular py-2 text-right">{c.margin_pct.toFixed(1)}%</td>
              <td className="tabular py-2 text-right">{formatNumber(c.units)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function ForecastMix({ data }: { data: AnalyticsDTO }) {
  const total = data.forecast_mix.reduce((s, m) => s + m.skus, 0) || 1;
  return (
    <ul className="space-y-3 text-sm">
      {data.forecast_mix.map((m) => (
        <li key={`${m.method}-${m.confidence}`}>
          <div className="flex justify-between">
            <span className="text-ink">
              {m.method.toLowerCase()} · {m.confidence === "LOW" ? "low confidence" : "high confidence"}
            </span>
            <span className="tabular text-ink-secondary">{formatNumber(m.skus)}</span>
          </div>
          <div className="mt-1 h-2 w-full rounded-full bg-elevated" aria-hidden="true">
            <div
              className="h-2 rounded-full"
              style={{
                width: `${(m.skus / total) * 100}%`,
                backgroundColor: m.confidence === "LOW" ? "var(--warning-text)" : "var(--brand-primary)",
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function LostSales({ data }: { data: AnalyticsDTO }) {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Products with the highest estimated lost revenue</caption>
      <thead>
        <tr className="text-left text-xs text-ink-secondary">
          <th scope="col" className="pb-2 font-medium">
            Product
          </th>
          <th scope="col" className="pb-2 font-medium">
            Store
          </th>
          <th scope="col" className="pb-2 text-right font-medium">
            Lost units
          </th>
          <th scope="col" className="pb-2 text-right font-medium">
            Lost revenue
          </th>
          <th scope="col" className="pb-2 text-right font-medium">
            Lost profit
          </th>
        </tr>
      </thead>
      <tbody>
        {data.top_lost_sales.map((l) => (
          <tr key={`${l.store.store_id}-${l.product.product_id}`} className="border-t border-divider">
            <td className="py-2 text-ink">{l.product.name}</td>
            <td className="py-2 text-ink-secondary">{l.store.name}</td>
            <td className="tabular py-2 text-right">{l.lost_units.toFixed(1)}</td>
            <td className="tabular py-2 text-right">{formatINR(l.lost_revenue)}</td>
            <td className="tabular py-2 text-right">{formatINR(l.lost_profit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AnalyticsPage() {
  const { user } = useAuth();
  const { storeId, period } = useShell();
  const scope = user?.role === "SUPER_ADMIN" ? storeId : (user?.store?.store_id ?? null);
  const analytics = useAnalytics({ store_id: scope ?? undefined, period });
  const data = analytics.data;

  let body: ReactNode;
  if (analytics.isPending) {
    body = (
      <div className="space-y-3" aria-busy="true">
        <SkeletonLine />
        <SkeletonLine width="70%" />
      </div>
    );
  } else if (analytics.error) {
    body = <ErrorState message={analytics.error.message} onRetry={() => void analytics.refetch()} />;
  } else if (data) {
    body = (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="ABC-XYZ classification" note="Store-SKUs by value share (ABC) and demand variability (XYZ).">
          {data.abc_xyz.length ? <AbcXyz data={data} /> : <EmptyState title="Not classified yet" />}
        </Section>
        <Section
          title="Forecast methods"
          note="Low confidence: stale or too little in-stock history — never transferred (D-04)."
        >
          {data.forecast_mix.length ? (
            <ForecastMix data={data} />
          ) : (
            <EmptyState title="No forecasts in the latest run" />
          )}
        </Section>
        <div className="lg:col-span-2">
          <Section title="Revenue and margin by category">
            {data.categories.length ? <Categories data={data} /> : <EmptyState title="No sales in this period" />}
          </Section>
        </div>
        <div className="lg:col-span-2">
          <Section title="Highest lost sales (latest run)" note="Lost revenue and lost profit are separate (rule 9).">
            {data.top_lost_sales.length ? <LostSales data={data} /> : <EmptyState title="No lost sales estimated" />}
          </Section>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm text-ink-secondary">
          {data?.store?.name ?? (scope === null ? "All stores" : "")}
          {data?.data_as_of ? ` · Data as of ${formatDateIST(data.data_as_of)}` : ""}
        </p>
      </header>
      {body}
    </div>
  );
}
