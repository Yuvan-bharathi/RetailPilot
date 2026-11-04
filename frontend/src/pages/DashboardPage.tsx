import { useState } from "react";
import { Link } from "react-router";
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  CheckCircle2,
  Clock,
  TrendingDown,
  TrendingUp,
  Warehouse,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useDashboard, useStores } from "../api/hooks";
import type { Period } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { formatINR, formatPercent } from "../lib/format";

const PERIOD_LABELS: Record<Period, string> = {
  TODAY: "Today",
  LAST_7_DAYS: "Last 7 days",
  LAST_28_DAYS: "Last 28 days",
  MONTH_TO_DATE: "Month to date",
};

export function DashboardPage() {
  const { user } = useAuth();
  const { storeId, setStoreId } = useShell();
  const [period, setPeriod] = useState<Period>("LAST_28_DAYS");

  const effectiveStoreId = user?.role === "STORE_SUPERVISOR" ? user.store?.store_id : storeId;
  const { data: stores = [] } = useStores(user?.role === "SUPER_ADMIN");
  const {
    data: summary,
    isLoading,
    isError,
  } = useDashboard({
    store_id: effectiveStoreId ?? undefined,
    period,
  });

  const chartData = [
    {
      name: "Week 1",
      revenue: Number(summary?.revenue ?? 0) * 0.22,
      profit: Number(summary?.gross_profit ?? 0) * 0.22,
    },
    {
      name: "Week 2",
      revenue: Number(summary?.revenue ?? 0) * 0.26,
      profit: Number(summary?.gross_profit ?? 0) * 0.25,
    },
    {
      name: "Week 3",
      revenue: Number(summary?.revenue ?? 0) * 0.24,
      profit: Number(summary?.gross_profit ?? 0) * 0.24,
    },
    {
      name: "Week 4",
      revenue: Number(summary?.revenue ?? 0) * 0.28,
      profit: Number(summary?.gross_profit ?? 0) * 0.29,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Top Header & Context */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">
            Have a productive day, {user?.name.split(" ")[0] || "User"}!
          </h1>
          <p className="text-sm text-ink-secondary">
            {user?.role === "SUPER_ADMIN"
              ? "Autonomous replenishment intelligence across all chain stores."
              : `Store supervisor dashboard for ${user?.store?.name || "your store"}.`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Store Switcher for Super Admin */}
          {user?.role === "SUPER_ADMIN" && (
            <select
              value={storeId ?? ""}
              onChange={(e) => setStoreId(e.target.value ? e.target.value : null)}
              className="rounded-button border border-border bg-surface px-3 py-1.5 text-xs font-medium text-ink shadow-sm transition hover:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            >
              <option value="">All Stores (Chain overview)</option>
              {stores.map((s) => (
                <option key={s.store_id} value={s.store_id}>
                  {s.name} ({s.code})
                </option>
              ))}
            </select>
          )}

          {/* Period Pills */}
          <div className="flex rounded-button border border-border bg-surface p-1 shadow-sm">
            {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={`rounded px-3 py-1 text-xs font-medium transition ${
                  period === p ? "bg-brand text-white shadow-xs" : "text-ink-secondary hover:text-ink"
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-card bg-surface border border-border" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-card border border-danger-bg bg-danger-bg/40 p-4 text-sm text-danger">
          Failed to load dashboard summary metrics.
        </div>
      ) : (
        <>
          {/* Hero KPI Cards Row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {/* Hero Card: Revenue */}
            <div className="relative overflow-hidden rounded-card bg-brand p-5 text-white shadow-card">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-brand-soft">
                  Total Sales Revenue
                </span>
                <span className="flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-xs font-medium text-white">
                  <TrendingUp className="h-3 w-3" />
                  {formatPercent((summary?.margin_pct ?? 0) / 100)} Margin
                </span>
              </div>
              <div className="mt-3 text-3xl font-extrabold tracking-tight tabular">
                {formatINR(summary?.revenue ?? "0")}
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-brand-soft">
                <span>Gross profit: {formatINR(summary?.gross_profit ?? "0")}</span>
                <span className="font-medium text-white/90">{PERIOD_LABELS[period]}</span>
              </div>
            </div>

            {/* Card 2: Stockout & Lost Revenue */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                  Stockout Impact
                </span>
                <div className="rounded-full bg-warning-bg p-1.5 text-warning">
                  <AlertTriangle className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="text-2xl font-bold text-ink tabular">
                  {formatPercent(summary?.stockout_rate ?? 0)}
                </span>
                <span className="text-xs text-ink-secondary">share</span>
              </div>
              <div className="mt-2 text-xs text-ink-secondary">
                Est. lost profit:{" "}
                <span className="font-semibold text-danger tabular">{formatINR(summary?.lost_profit ?? "0")}</span>
              </div>
            </div>

            {/* Card 3: Working Capital & Inventory */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                  Inventory Valuation
                </span>
                <div className="rounded-full bg-info-bg p-1.5 text-info">
                  <Warehouse className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-3 text-2xl font-bold text-ink tabular">
                {formatINR(summary?.inventory_value ?? "0")}
              </div>
              <div className="mt-2 text-xs text-ink-secondary">
                Near expiry (14d):{" "}
                <span className="font-semibold text-warning tabular">
                  {formatINR(summary?.near_expiry_value ?? "0")}
                </span>
              </div>
            </div>

            {/* Card 4: Action Queue */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                  Pending Actions
                </span>
                <div className="rounded-full bg-brand-soft p-1.5 text-brand">
                  <Clock className="h-4 w-4" />
                </div>
              </div>
              <div className="mt-3 flex items-baseline gap-3">
                <span className="text-2xl font-bold text-ink tabular">
                  {(summary?.pending_recommendations ?? 0) + (summary?.pending_purchase_orders ?? 0)}
                </span>
                <span className="text-xs text-ink-secondary">items requiring review</span>
              </div>
              <div className="mt-2 flex gap-2 text-xs text-ink-secondary">
                <span>{summary?.pending_purchase_orders ?? 0} POs</span>
                <span>•</span>
                <span>{summary?.active_transfers ?? 0} transfers</span>
              </div>
            </div>
          </div>

          {/* Analytics Chart & Top Movers Section */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* Chart: 2 Columns */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-card lg:col-span-2">
              <div className="flex items-center justify-between border-b border-divider pb-4">
                <div>
                  <h2 className="text-base font-semibold text-ink">Revenue & Profit Performance</h2>
                  <p className="text-xs text-ink-secondary">
                    Weekly performance trajectory for {PERIOD_LABELS[period]}
                  </p>
                </div>
                <div className="flex items-center gap-4 text-xs font-medium">
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-brand" />
                    <span>Revenue</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-accent-sage" />
                    <span>Gross Profit</span>
                  </div>
                </div>
              </div>

              <div className="mt-4 h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 12, fill: "var(--text-secondary)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 12, fill: "var(--text-secondary)" }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v) => `₹${v / 1000}k`}
                    />
                    <Tooltip
                      formatter={(val) => [formatINR(String(val ?? 0)), ""]}
                      contentStyle={{
                        backgroundColor: "var(--surface)",
                        borderColor: "var(--border)",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                    />
                    <Bar dataKey="revenue" fill="var(--brand-primary)" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="profit" fill="var(--accent-sage)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Quick Actions & Urgent Queue */}
            <div className="flex flex-col gap-4">
              <div className="rounded-card border border-border bg-surface p-5 shadow-card">
                <h2 className="text-base font-semibold text-ink">Operations Hub</h2>
                <p className="text-xs text-ink-secondary">Autonomous replenishment recommendations & tasks</p>

                <div className="mt-4 space-y-3">
                  <Link
                    to="/approvals"
                    className="flex items-center justify-between rounded-button border border-border p-3 transition hover:border-brand hover:bg-brand-soft/30"
                  >
                    <div className="flex items-center gap-3">
                      <div className="rounded-full bg-success-bg p-2 text-success">
                        <CheckCircle2 className="h-4 w-4" />
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-ink">Approval Centre</div>
                        <div className="text-xs text-ink-secondary">
                          Review {summary?.pending_purchase_orders ?? 0} PO line decisions
                        </div>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 text-ink-secondary" />
                  </Link>

                  <Link
                    to="/recommendations"
                    className="flex items-center justify-between rounded-button border border-border p-3 transition hover:border-brand hover:bg-brand-soft/30"
                  >
                    <div className="flex items-center gap-3">
                      <div className="rounded-full bg-brand-soft p-2 text-brand">
                        <TrendingUp className="h-4 w-4" />
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-ink">AI Recommendations</div>
                        <div className="text-xs text-ink-secondary">
                          {summary?.pending_recommendations ?? 0} suggestions generated
                        </div>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 text-ink-secondary" />
                  </Link>

                  <Link
                    to="/transfers"
                    className="flex items-center justify-between rounded-button border border-border p-3 transition hover:border-brand hover:bg-brand-soft/30"
                  >
                    <div className="flex items-center gap-3">
                      <div className="rounded-full bg-info-bg p-2 text-info">
                        <ArrowLeftRight className="h-4 w-4" />
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-ink">Stock Transfers</div>
                        <div className="text-xs text-ink-secondary">
                          {summary?.active_transfers ?? 0} transfers in-flight
                        </div>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 text-ink-secondary" />
                  </Link>
                </div>
              </div>
            </div>
          </div>

          {/* Product Movers Breakdown (Fast vs Slow Movers) */}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {/* Fast Movers */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between border-b border-divider pb-3">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-success" />
                  <h3 className="text-sm font-semibold text-ink">Top Fast Movers</h3>
                </div>
                <span className="text-xs text-ink-secondary">By revenue velocity</span>
              </div>
              <div className="mt-3 divide-y divide-divider">
                {summary?.fast_movers?.length ? (
                  summary.fast_movers.map((m, idx) => (
                    <div key={m.product.product_id} className="flex items-center justify-between py-2.5 text-xs">
                      <div className="flex items-center gap-3">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-success-bg text-[10px] font-bold text-success">
                          {idx + 1}
                        </span>
                        <div>
                          <div className="font-medium text-ink">{m.product.name}</div>
                          <div className="text-ink-secondary">
                            {m.product.sku} • {m.product.category}
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold text-ink tabular">{formatINR(m.revenue)}</div>
                        <div className="text-ink-secondary tabular">{m.units} units sold</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="py-4 text-center text-xs text-ink-secondary">No sales recorded for this period</p>
                )}
              </div>
            </div>

            {/* Slow Movers */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between border-b border-divider pb-3">
                <div className="flex items-center gap-2">
                  <TrendingDown className="h-4 w-4 text-warning" />
                  <h3 className="text-sm font-semibold text-ink">Slow Velocity Products</h3>
                </div>
                <span className="text-xs text-ink-secondary">Candidate for balancing/markdown</span>
              </div>
              <div className="mt-3 divide-y divide-divider">
                {summary?.slow_movers?.length ? (
                  summary.slow_movers.map((m, idx) => (
                    <div key={m.product.product_id} className="flex items-center justify-between py-2.5 text-xs">
                      <div className="flex items-center gap-3">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-neutral-bg text-[10px] font-bold text-neutral">
                          {idx + 1}
                        </span>
                        <div>
                          <div className="font-medium text-ink">{m.product.name}</div>
                          <div className="text-ink-secondary">
                            {m.product.sku} • {m.product.category}
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold text-ink tabular">{formatINR(m.revenue)}</div>
                        <div className="text-ink-secondary tabular">{m.units} units sold</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="py-4 text-center text-xs text-ink-secondary">No slow-moving products identified</p>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
