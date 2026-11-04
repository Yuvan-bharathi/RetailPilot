import { useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Filter,
  Layers,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useDashboard } from "../api/hooks";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { formatINRCompact, formatPercent } from "../lib/format";

const ABC_XYZ_DATA = [
  {
    segment: "AX",
    count: 342,
    value: "₹18.4L",
    desc: "High revenue, steady demand (Auto-replenish)",
    status: "Optimal",
  },
  { segment: "AY", count: 184, value: "₹11.2L", desc: "High revenue, seasonal variability", status: "Buffer stock" },
  { segment: "AZ", count: 68, value: "₹4.6L", desc: "High revenue, erratic demand", status: "Review weekly" },
  { segment: "BX", count: 215, value: "₹4.2L", desc: "Medium revenue, steady demand", status: "Optimal" },
  { segment: "BY", count: 142, value: "₹2.8L", desc: "Medium revenue, moderate variance", status: "Monitor" },
  { segment: "BZ", count: 96, value: "₹1.1L", desc: "Medium revenue, unpredictable", status: "Buffer stock" },
  { segment: "CX", count: 88, value: "₹0.3L", desc: "Low revenue, steady demand", status: "Standard reorder" },
  { segment: "CY", count: 120, value: "₹0.2L", desc: "Low revenue, seasonal demand", status: "Candidate delist" },
  { segment: "CZ", count: 74, value: "₹0.1L", desc: "Low revenue, erratic demand", status: "Delist / Phase out" },
];

const CATEGORY_MARGIN_DATA = [
  { category: "Grocery", revenue: 16.2, profit: 3.4, margin: 21.0 },
  { category: "Beverages", revenue: 9.8, profit: 2.8, margin: 28.5 },
  { category: "Personal Care", revenue: 7.4, profit: 2.5, margin: 33.7 },
  { category: "Home Care", revenue: 5.6, profit: 1.4, margin: 25.0 },
  { category: "Dairy & Frozen", revenue: 4.8, profit: 0.9, margin: 18.7 },
  { category: "Others", revenue: 2.4, profit: 0.5, margin: 20.8 },
];

const FORECAST_ACCURACY_DATA = [
  { week: "W1", accuracy: 91.2, stockouts: 18 },
  { week: "W2", accuracy: 92.4, stockouts: 15 },
  { week: "W3", accuracy: 93.1, stockouts: 12 },
  { week: "W4", accuracy: 93.8, stockouts: 11 },
  { week: "W5", accuracy: 94.5, stockouts: 9 },
  { week: "W6", accuracy: 94.0, stockouts: 10 },
  { week: "W7", accuracy: 94.8, stockouts: 8 },
  { week: "W8", accuracy: 95.2, stockouts: 7 },
  { week: "W9", accuracy: 95.8, stockouts: 6 },
  { week: "W10", accuracy: 96.1, stockouts: 5 },
  { week: "W11", accuracy: 96.4, stockouts: 4 },
  { week: "W12", accuracy: 96.8, stockouts: 3 },
];

const LOST_SALES_IMPACT = [
  {
    sku: "SKU-1044",
    name: "Whole Milk 1L",
    category: "Dairy",
    stockoutDays: 4,
    unitsLost: 160,
    lostRev: "₹10,400",
    rootCause: "Supplier delay",
  },
  {
    sku: "SKU-2091",
    name: "Atta Wheat Flour 5kg",
    category: "Grocery",
    stockoutDays: 3,
    unitsLost: 90,
    lostRev: "₹24,750",
    rootCause: "Demand surge",
  },
  {
    sku: "SKU-3120",
    name: "Dishwashing Gel 500ml",
    category: "Home Care",
    stockoutDays: 2,
    unitsLost: 45,
    lostRev: "₹5,850",
    rootCause: "Backroom miscount",
  },
  {
    sku: "SKU-4822",
    name: "Green Tea Bags 25s",
    category: "Beverages",
    stockoutDays: 5,
    unitsLost: 55,
    lostRev: "₹9,350",
    rootCause: "MOQ constraint",
  },
  {
    sku: "SKU-5110",
    name: "Shampoo 340ml",
    category: "Personal Care",
    stockoutDays: 2,
    unitsLost: 30,
    lostRev: "₹8,700",
    rootCause: "Lead time variance",
  },
];

export function AnalyticsPage() {
  const { user } = useAuth();
  const { storeId, period } = useShell();
  const [selectedSegment, setSelectedSegment] = useState<string>("ALL");

  const effectiveStoreId = user?.role === "STORE_SUPERVISOR" ? user.store?.store_id : storeId;
  const { data: summary } = useDashboard({
    store_id: effectiveStoreId ?? undefined,
    period,
  });

  const filteredSegments =
    selectedSegment === "ALL" ? ABC_XYZ_DATA : ABC_XYZ_DATA.filter((s) => s.segment.startsWith(selectedSegment));

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight text-ink">
              {user?.role === "SUPER_ADMIN" ? "Chain Analytics & Intelligence" : "Store Performance Reports"}
            </h1>
            <span className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold text-brand">
              {user?.role === "SUPER_ADMIN" ? "Network View" : (user?.store?.name ?? "Store Level")}
            </span>
          </div>
          <p className="text-sm text-ink-secondary">
            Cross-category demand velocity, ABC-XYZ assortment classification, and lost revenue diagnostics.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-button border border-border bg-surface px-3 py-1.5 text-xs font-medium text-ink shadow-card">
            <BarChart3 className="h-4 w-4 text-brand" />
            <span>Telemetry Mode: Realtime Sync</span>
          </div>
        </div>
      </div>

      {/* KPI Highlights */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* KPI 1 */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Revenue Velocity</span>
            <div className="rounded-full bg-brand-soft p-1.5 text-brand">
              <TrendingUp className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-2xl font-bold text-ink tabular">
            {summary?.revenue ? formatINRCompact(summary.revenue) : "₹42.8L"}
          </div>
          <div className="mt-1 flex items-center gap-1 text-xs text-success">
            <ArrowUpRight className="h-3.5 w-3.5" />
            <span className="font-semibold">+8.4%</span>
            <span className="text-ink-secondary">vs previous period</span>
          </div>
        </div>

        {/* KPI 2 */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Stockout Lost Sales
            </span>
            <div className="rounded-full bg-warning-bg p-1.5 text-warning">
              <AlertTriangle className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-2xl font-bold text-ink tabular">
            {summary?.lost_revenue ? formatINRCompact(summary.lost_revenue) : "₹1.45L"}
          </div>
          <div className="mt-1 flex items-center gap-1 text-xs text-success">
            <ArrowDownRight className="h-3.5 w-3.5" />
            <span className="font-semibold">-18.2%</span>
            <span className="text-ink-secondary">lower with AI balancing</span>
          </div>
        </div>

        {/* KPI 3 */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Forecast Accuracy</span>
            <div className="rounded-full bg-success-bg p-1.5 text-success">
              <CheckCircle2 className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-2xl font-bold text-ink tabular">96.8%</div>
          <div className="mt-1 flex items-center gap-1 text-xs text-success">
            <span className="font-semibold">WMAPE: 3.2%</span>
            <span className="text-ink-secondary">across top 100 SKUs</span>
          </div>
        </div>

        {/* KPI 4 */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Assortment Health</span>
            <div className="rounded-full bg-info-bg p-1.5 text-info">
              <Sparkles className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-2xl font-bold text-ink tabular">
            {summary ? formatPercent(1 - summary.stockout_rate) : "95.6%"}
          </div>
          <div className="mt-1 flex items-center gap-1 text-xs text-ink-secondary">
            <span>In-stock availability</span>
          </div>
        </div>
      </div>

      {/* Analytics Charts Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Chart 1: Category Margin Contribution */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between border-b border-divider pb-3">
            <div>
              <h2 className="text-base font-semibold text-ink">Category Revenue & Gross Margin</h2>
              <p className="text-xs text-ink-secondary">Revenue in ₹ Lakhs vs Gross Profit Margin %</p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <div className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: "var(--brand-primary)" }} />
                <span className="text-ink-secondary">Revenue (₹L)</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: "var(--accent-sage)" }} />
                <span className="text-ink-secondary">Margin %</span>
              </div>
            </div>
          </div>

          <div className="mt-4 h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={CATEGORY_MARGIN_DATA} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="category"
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="left"
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => `₹${v}L`}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip
                  formatter={(val, name) => [
                    name === "revenue" ? `₹${val}L` : `${val}%`,
                    name === "revenue" ? "Revenue" : "Gross Margin",
                  ]}
                  contentStyle={{
                    backgroundColor: "var(--surface)",
                    borderColor: "var(--border)",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
                <Bar yAxisId="left" dataKey="revenue" fill="var(--brand-primary)" radius={[4, 4, 0, 0]} />
                <Bar yAxisId="right" dataKey="margin" fill="var(--accent-sage)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Forecast Accuracy Trajectory */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between border-b border-divider pb-3">
            <div>
              <h2 className="text-base font-semibold text-ink">Forecast Reliability & Stockout Decline</h2>
              <p className="text-xs text-ink-secondary">12-week progression after multi-agent orchestration</p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <div className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: "var(--brand-primary)" }} />
                <span className="text-ink-secondary">Accuracy %</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: "var(--danger-text)" }} />
                <span className="text-ink-secondary">Stockouts</span>
              </div>
            </div>
          </div>

          <div className="mt-4 h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={FORECAST_ACCURACY_DATA} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="week"
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="left"
                  domain={[85, 100]}
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => `${v}%`}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  domain={[0, 20]}
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--surface)",
                    borderColor: "var(--border)",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="accuracy"
                  stroke="var(--brand-primary)"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "var(--brand-primary)" }}
                  name="Accuracy %"
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="stockouts"
                  stroke="var(--danger-text)"
                  strokeWidth={2}
                  strokeDasharray="3 3"
                  dot={{ r: 3, fill: "var(--danger-text)" }}
                  name="Stockout Events"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ABC-XYZ Matrix Breakdown */}
      <div className="rounded-card border border-border bg-surface p-5 shadow-card">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-divider pb-4">
          <div>
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-brand" />
              <h2 className="text-base font-semibold text-ink">ABC-XYZ Assortment Classification Matrix</h2>
            </div>
            <p className="text-xs text-ink-secondary">
              Product segmentation by revenue share (A: 80%, B: 15%, C: 5%) and demand variability (X: stable, Y:
              seasonal, Z: erratic)
            </p>
          </div>

          <div className="flex items-center gap-1.5 rounded-button border border-border bg-app p-1 text-xs">
            <Filter className="ml-1.5 h-3.5 w-3.5 text-ink-secondary" />
            {["ALL", "A", "B", "C"].map((tier) => (
              <button
                key={tier}
                type="button"
                onClick={() => setSelectedSegment(tier)}
                className={`rounded px-2.5 py-1 font-medium transition ${
                  selectedSegment === tier ? "bg-brand text-white shadow-xs" : "text-ink-secondary hover:text-ink"
                }`}
              >
                {tier === "ALL" ? "All Segments" : `Class ${tier}`}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-divider text-ink-secondary">
                <th className="pb-2.5 font-medium">Segment</th>
                <th className="pb-2.5 font-medium">Active SKUs</th>
                <th className="pb-2.5 font-medium">Inventory Value</th>
                <th className="pb-2.5 font-medium">Strategy & Characteristics</th>
                <th className="pb-2.5 font-medium">Operational Recommendation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider">
              {filteredSegments.map((row) => (
                <tr key={row.segment} className="hover:bg-brand-soft/20">
                  <td className="py-2.5">
                    <span className="inline-flex h-6 w-8 items-center justify-center rounded font-bold bg-brand-soft text-brand">
                      {row.segment}
                    </span>
                  </td>
                  <td className="py-2.5 font-semibold text-ink tabular">{row.count} SKUs</td>
                  <td className="py-2.5 text-ink font-medium tabular">{row.value}</td>
                  <td className="py-2.5 text-ink-secondary">{row.desc}</td>
                  <td className="py-2.5">
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
                        row.status === "Optimal"
                          ? "bg-success-bg text-success"
                          : row.status.includes("Buffer")
                            ? "bg-info-bg text-info"
                            : row.status.includes("Delist")
                              ? "bg-danger-bg text-danger"
                              : "bg-warning-bg text-warning"
                      }`}
                    >
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Lost Sales Impact Table */}
      <div className="rounded-card border border-border bg-surface p-5 shadow-card">
        <div className="border-b border-divider pb-3">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-danger" />
            <h2 className="text-base font-semibold text-ink">Stockout Lost Sales Diagnostics</h2>
          </div>
          <p className="text-xs text-ink-secondary">
            Estimated uncaptured revenue and root cause attribution across high-velocity products.
          </p>
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-divider text-ink-secondary">
                <th className="pb-2 font-medium">SKU</th>
                <th className="pb-2 font-medium">Product</th>
                <th className="pb-2 font-medium">Category</th>
                <th className="pb-2 font-medium">Days Out of Stock</th>
                <th className="pb-2 font-medium">Est. Units Lost</th>
                <th className="pb-2 font-medium">Lost Revenue</th>
                <th className="pb-2 font-medium">Root Cause</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider">
              {LOST_SALES_IMPACT.map((item) => (
                <tr key={item.sku} className="hover:bg-brand-soft/20">
                  <td className="py-2.5 font-semibold text-ink">{item.sku}</td>
                  <td className="py-2.5 text-ink font-medium">{item.name}</td>
                  <td className="py-2.5 text-ink-secondary">{item.category}</td>
                  <td className="py-2.5 text-danger font-semibold tabular">{item.stockoutDays} days</td>
                  <td className="py-2.5 text-ink tabular">{item.unitsLost}</td>
                  <td className="py-2.5 font-bold text-danger tabular">{item.lostRev}</td>
                  <td className="py-2.5">
                    <span className="rounded bg-attention-bg px-2 py-0.5 text-[10px] font-semibold text-attention">
                      {item.rootCause}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
