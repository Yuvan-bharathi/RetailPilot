import { ChevronsLeft, ChevronsRight, LogOut, ShoppingBasket } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";

import { useLatestRun, useStores } from "../api/hooks";
import type { MeDTO, Period } from "../api/types";
import { navFor } from "../app/nav";
import { useShell } from "../app/ShellContext";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { formatDateTimeIST } from "../lib/format";

const PERIODS: Array<{ value: Period; label: string }> = [
  { value: "TODAY", label: "Today" },
  { value: "LAST_7_DAYS", label: "Last 7 days" },
  { value: "LAST_28_DAYS", label: "Last 28 days" },
  { value: "MONTH_TO_DATE", label: "Month to date" },
];

/** Sidebar collapses automatically below 1280 px; the user can still toggle it. */
const NARROW = "(max-width: 1279px)";

function Sidebar({ user, collapsed, onToggle }: { user: MeDTO; collapsed: boolean; onToggle: () => void }) {
  const items = navFor(user.role);
  return (
    <aside
      className="sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-sidebar transition-[width]"
      style={{ width: collapsed ? "var(--sidebar-collapsed-width)" : "var(--sidebar-width)" }}
    >
      <div className="flex h-16 items-center gap-2 px-4">
        <ShoppingBasket aria-hidden="true" className="shrink-0 text-brand" size={24} />
        {collapsed ? <span className="sr-only">RetailPilot AI</span> : <span className="font-semibold text-ink">RetailPilot AI</span>}
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2">
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={item.path}>
              <NavLink
                to={item.path}
                end={item.path === "/"}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  `flex h-10 items-center gap-3 rounded-button px-3 text-sm ${
                    isActive ? "bg-brand-soft font-semibold text-brand" : "text-ink-secondary hover:bg-surface hover:text-ink"
                  }`
                }
              >
                <item.icon aria-hidden="true" size={18} className="shrink-0" />
                {collapsed ? <span className="sr-only">{item.label}</span> : <span className="truncate">{item.label}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="m-2 flex h-10 items-center gap-3 rounded-button px-3 text-sm text-ink-secondary hover:bg-surface hover:text-ink"
      >
        {collapsed ? <ChevronsRight aria-hidden="true" size={18} /> : <ChevronsLeft aria-hidden="true" size={18} />}
        {collapsed ? <span className="sr-only">Expand sidebar</span> : <span>Collapse sidebar</span>}
      </button>
    </aside>
  );
}

function Header({ user, title, onSignOut }: { user: MeDTO; title: string; onSignOut: () => void }) {
  const { storeId, setStoreId, period, setPeriod } = useShell();
  const isAdmin = user.role === "SUPER_ADMIN";
  const stores = useStores(isAdmin);
  const run = useLatestRun();

  return (
    <header className="sticky top-0 z-40 flex min-h-16 flex-wrap items-center gap-3 border-b border-border bg-surface px-6 py-2">
      <h1 className="mr-auto text-[22px] leading-7 font-semibold text-ink">{title}</h1>
      {isAdmin ? (
        <>
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            Store
            <select
              className="h-9 rounded-input border border-border bg-surface px-2 text-ink"
              value={storeId ?? ""}
              onChange={(e) => setStoreId(e.target.value || null)}
            >
              <option value="">All stores</option>
              {stores.data?.map((s) => (
                <option key={s.store_id} value={s.store_id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            Period
            <select
              className="h-9 rounded-input border border-border bg-surface px-2 text-ink"
              value={period}
              onChange={(e) => setPeriod(e.target.value as Period)}
            >
              {PERIODS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        </>
      ) : user.store ? (
        <span className="text-sm text-ink-secondary">{user.store.name}</span>
      ) : null}
      <span className="text-xs text-ink-secondary" aria-live="polite">
        {run.data ? `Data as of last run: ${formatDateTimeIST(run.data.finished_at)}` : "Data as of last run: …"}
      </span>
      <div className="flex items-center gap-2 border-l border-divider pl-3">
        <span className="text-sm">
          <span className="block font-medium text-ink">{user.name}</span>
          <span className="block text-xs text-ink-secondary">{isAdmin ? "Super Admin" : "Store Supervisor"}</span>
        </span>
        <button
          type="button"
          onClick={onSignOut}
          className="rounded-button p-2 text-ink-secondary hover:bg-elevated hover:text-ink"
          aria-label="Sign out"
        >
          <LogOut aria-hidden="true" size={18} />
        </button>
      </div>
    </header>
  );
}

export function AppShell({ user, onSignOut, children }: { user: MeDTO; onSignOut: () => void; children: ReactNode }) {
  const narrow = useMediaQuery(NARROW);
  const [override, setOverride] = useState<boolean | null>(null);
  const collapsed = override ?? narrow;
  const location = useLocation();
  const current = navFor(user.role).find((i) => (i.path === "/" ? location.pathname === "/" : location.pathname.startsWith(i.path)));
  const title = location.pathname === "/components" ? "Design system" : (current?.label ?? "RetailPilot AI");

  return (
    <div className="flex min-h-screen bg-app">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <Sidebar user={user} collapsed={collapsed} onToggle={() => setOverride(!collapsed)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header user={user} title={title} onSignOut={onSignOut} />
        <main id="main" className="min-w-0 flex-1 p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
