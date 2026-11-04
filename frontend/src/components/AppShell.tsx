import { Bell, Check, ChevronsLeft, ChevronsRight, LogOut, ShoppingBasket, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";

import { useLatestRun, useNotifications, useStores } from "../api/hooks";
import type { MeDTO, Period } from "../api/types";
import { useApi } from "../app/ApiContext";
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
      <div className="flex h-16 items-center gap-2.5 px-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-card bg-brand text-surface shadow-card shrink-0">
          <ShoppingBasket aria-hidden="true" size={20} />
        </div>
        {collapsed ? (
          <span className="sr-only">RetailPilot AI</span>
        ) : (
          <div className="flex flex-col">
            <span className="font-bold text-sm tracking-tight text-ink">RetailPilot AI</span>
            <span className="text-[10px] font-medium text-ink-secondary">Autonomous Replenishment</span>
          </div>
        )}
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-2">
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={item.path}>
              <NavLink
                to={item.path}
                end={item.path === "/"}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  `flex h-10 items-center gap-3 rounded-button px-3 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-brand text-surface shadow-card"
                      : "text-ink-secondary hover:bg-surface hover:text-ink"
                  }`
                }
              >
                <item.icon aria-hidden="true" size={18} className="shrink-0" />
                {collapsed ? (
                  <span className="sr-only">{item.label}</span>
                ) : (
                  <span className="truncate">{item.label}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="m-2 flex h-10 items-center gap-3 rounded-button px-3 text-sm text-ink-secondary hover:bg-surface hover:text-ink transition-colors"
      >
        {collapsed ? <ChevronsRight aria-hidden="true" size={18} /> : <ChevronsLeft aria-hidden="true" size={18} />}
        {collapsed ? <span className="sr-only">Expand sidebar</span> : <span>Collapse sidebar</span>}
      </button>
    </aside>
  );
}

function NotificationsPopover({ onClose }: { onClose: () => void }) {
  const api = useApi();
  const notifsQuery = useNotifications(false);
  const notifs = notifsQuery.data ?? [];

  const handleMarkRead = async (id: string) => {
    try {
      await api.markNotificationRead(id);
      void notifsQuery.refetch();
    } catch {
      // ignore
    }
  };

  return (
    <div className="absolute right-0 top-12 z-50 w-80 rounded-modal border border-border bg-surface p-4 shadow-dropdown">
      <div className="flex items-center justify-between border-b border-border pb-2.5">
        <span className="font-semibold text-sm text-ink">Notifications</span>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-ink-secondary hover:bg-elevated hover:text-ink"
        >
          <X size={16} />
        </button>
      </div>

      <div className="mt-2 max-h-72 overflow-y-auto divide-y divide-border">
        {notifs.length === 0 ? (
          <p className="py-6 text-center text-xs text-ink-secondary">No recent notifications</p>
        ) : (
          notifs.map((n) => (
            <div key={n.notification_id} className="py-2.5 text-xs">
              <div className="flex items-start justify-between gap-2">
                <p className={`text-ink ${n.read_at ? "text-ink-secondary" : "font-medium"}`}>{n.message}</p>
                {!n.read_at && (
                  <button
                    type="button"
                    onClick={() => void handleMarkRead(n.notification_id)}
                    className="shrink-0 rounded p-1 text-brand hover:bg-brand-soft"
                    title="Mark as read"
                  >
                    <Check size={14} />
                  </button>
                )}
              </div>
              <span className="mt-1 block text-[10px] text-ink-secondary tabular">
                {formatDateTimeIST(n.created_at)}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function Header({ user, title, onSignOut }: { user: MeDTO; title: string; onSignOut: () => void }) {
  const { storeId, setStoreId, period, setPeriod } = useShell();
  const isAdmin = user.role === "SUPER_ADMIN";
  const stores = useStores(isAdmin);
  const run = useLatestRun();
  const notifs = useNotifications(true);
  const [showNotifs, setShowNotifs] = useState(false);

  const unreadCount = notifs.data?.length ?? 0;

  return (
    <header className="sticky top-0 z-40 flex min-h-16 flex-wrap items-center gap-3 border-b border-border bg-surface px-6 py-2">
      <h1 className="mr-auto text-[20px] font-bold tracking-tight text-ink">{title}</h1>
      {isAdmin ? (
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
            Store
            <select
              className="h-8 rounded-input border border-border bg-surface px-2.5 text-xs text-ink focus:outline-none"
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
          <label className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
            Period
            <select
              className="h-8 rounded-input border border-border bg-surface px-2.5 text-xs text-ink focus:outline-none"
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
        </div>
      ) : user.store ? (
        <span className="text-sm text-ink-secondary">{user.store.name}</span>
      ) : null}

      <span className="text-xs text-ink-secondary" aria-live="polite">
        {run.data ? `Data as of last run: ${formatDateTimeIST(run.data.finished_at)}` : "Data as of last run: …"}
      </span>

      {/* Notifications Button & Popover */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setShowNotifs(!showNotifs)}
          className="relative rounded-button p-2 text-ink-secondary hover:bg-elevated hover:text-ink transition-colors"
          aria-label="View notifications"
        >
          <Bell size={18} />
          {unreadCount > 0 && (
            <span className="absolute top-1.5 right-1.5 flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-brand opacity-75 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
            </span>
          )}
        </button>
        {showNotifs && <NotificationsPopover onClose={() => setShowNotifs(false)} />}
      </div>

      {/* User Info & Logout */}
      <div className="flex items-center gap-2 border-l border-divider pl-3">
        <div className="text-right">
          <span className="block text-xs font-semibold text-ink">{user.name}</span>
          <span className="block text-[11px] text-ink-secondary">{isAdmin ? "Super Admin" : "Store Supervisor"}</span>
        </div>
        <button
          type="button"
          onClick={onSignOut}
          className="rounded-button p-2 text-ink-secondary hover:bg-danger-bg hover:text-danger transition-colors"
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
  const current = navFor(user.role).find((i) =>
    i.path === "/" ? location.pathname === "/" : location.pathname.startsWith(i.path),
  );
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
