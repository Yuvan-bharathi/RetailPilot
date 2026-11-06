/**
 * One navigation map for both roles (docs/03-design-system.md §5). Items a role cannot access are hidden,
 * never shown disabled. Labels may differ by role (e.g. "Business overview" vs "Store overview").
 */
import {
  ArrowLeftRight,
  Bot,
  GitBranch,
  ListChecks,
  MessageSquareText,
  ScrollText,
  Workflow,
  BarChart3,
  Building2,
  CheckCircle2,
  ClipboardList,
  LayoutDashboard,
  type LucideIcon,
  PackageCheck,
  Settings,
  Sparkles,
  Warehouse,
} from "lucide-react";

import type { Role } from "../api/types";

export interface NavItem {
  path: string;
  icon: LucideIcon;
  label: Record<Role, string | null>; // null = hidden for that role
  /** Sidebar group heading (the agent console, docs/09 §2). */
  group?: "Agents";
}

const ADMIN_ONLY = (label: string): Record<Role, string | null> => ({ SUPER_ADMIN: label, STORE_SUPERVISOR: null });

export const NAV_ITEMS: NavItem[] = [
  { path: "/", icon: LayoutDashboard, label: { SUPER_ADMIN: "Business overview", STORE_SUPERVISOR: "Store overview" } },
  { path: "/stores", icon: Building2, label: { SUPER_ADMIN: "Stores", STORE_SUPERVISOR: null } },
  { path: "/inventory", icon: Warehouse, label: { SUPER_ADMIN: "Inventory", STORE_SUPERVISOR: "Inventory" } },
  {
    path: "/recommendations",
    icon: Sparkles,
    label: { SUPER_ADMIN: "AI recommendations", STORE_SUPERVISOR: "AI recommendations" },
  },
  {
    path: "/transfers",
    icon: ArrowLeftRight,
    label: { SUPER_ADMIN: "Stock transfers", STORE_SUPERVISOR: "Stock transfers" },
  },
  {
    path: "/purchase-orders",
    icon: ClipboardList,
    label: { SUPER_ADMIN: "Purchase orders", STORE_SUPERVISOR: "Purchase orders" },
  },
  { path: "/approvals", icon: CheckCircle2, label: { SUPER_ADMIN: "Approvals", STORE_SUPERVISOR: "Approvals" } },
  { path: "/goods-receipt", icon: PackageCheck, label: { SUPER_ADMIN: null, STORE_SUPERVISOR: "Goods receipt" } },
  { path: "/analytics", icon: BarChart3, label: { SUPER_ADMIN: "Analytics", STORE_SUPERVISOR: "Store reports" } },
  {
    path: "/ask",
    icon: MessageSquareText,
    label: { SUPER_ADMIN: "Ask RetailPilot", STORE_SUPERVISOR: "Ask RetailPilot" },
  },
  // Agent console (docs/09): replaces "System monitoring"; Super Admin only — hidden, not disabled, for supervisors
  { path: "/agents", icon: Bot, label: ADMIN_ONLY("Overview"), group: "Agents" },
  { path: "/agents/pipeline", icon: Workflow, label: ADMIN_ONLY("Pipeline"), group: "Agents" },
  { path: "/agents/flow", icon: GitBranch, label: ADMIN_ONLY("Visual flow"), group: "Agents" },
  { path: "/agents/logs", icon: ScrollText, label: ADMIN_ONLY("Logs"), group: "Agents" },
  { path: "/agents/decisions", icon: ListChecks, label: ADMIN_ONLY("Decisions"), group: "Agents" },
  { path: "/settings", icon: Settings, label: { SUPER_ADMIN: "Settings", STORE_SUPERVISOR: "Profile" } },
];

export interface VisibleNavItem {
  path: string;
  icon: LucideIcon;
  label: string;
  group?: "Agents";
}

export function navFor(role: Role): VisibleNavItem[] {
  return NAV_ITEMS.flatMap((item) => {
    const label = item.label[role];
    return label ? [{ path: item.path, icon: item.icon, label, group: item.group }] : [];
  });
}

/** The nav item owning a path: exact match, else the longest prefix ("/agents/stock_balancing" → "/agents"). */
export function navItemFor(path: string): NavItem | undefined {
  const exact = NAV_ITEMS.find((n) => n.path === path);
  if (exact) return exact;
  return NAV_ITEMS.filter((n) => n.path !== "/" && path.startsWith(n.path + "/")).sort(
    (a, b) => b.path.length - a.path.length,
  )[0];
}

/** Header title for a path; grouped items are prefixed ("Agents · Logs"). */
export function titleFor(role: Role, path: string): string | null {
  const item = navItemFor(path);
  const label = item?.label[role];
  if (!item || !label) return null;
  return item.group ? item.group + " · " + label : label;
}

export function canAccess(role: Role, path: string): boolean {
  if (path === "/components") return true; // design-system demo page (development aid)
  const item = navItemFor(path);
  return item !== undefined && item.label[role] !== null;
}
