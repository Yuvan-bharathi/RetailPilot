/**
 * One navigation map for both roles (docs/03-design-system.md §5). Items a role cannot access are hidden,
 * never shown disabled. Labels may differ by role (e.g. "Business overview" vs "Store overview").
 */
import {
  ArrowLeftRight,
  BarChart3,
  Building2,
  CheckCircle2,
  ClipboardList,
  LayoutDashboard,
  type LucideIcon,
  PackageCheck,
  Settings,
  Sparkles,
  Activity,
  Warehouse,
} from "lucide-react";

import type { Role } from "../api/types";

export interface NavItem {
  path: string;
  icon: LucideIcon;
  label: Record<Role, string | null>; // null = hidden for that role
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/", icon: LayoutDashboard, label: { SUPER_ADMIN: "Business overview", STORE_SUPERVISOR: "Store overview" } },
  { path: "/stores", icon: Building2, label: { SUPER_ADMIN: "Stores", STORE_SUPERVISOR: null } },
  { path: "/inventory", icon: Warehouse, label: { SUPER_ADMIN: "Inventory", STORE_SUPERVISOR: "Inventory" } },
  {
    path: "/recommendations",
    icon: Sparkles,
    label: { SUPER_ADMIN: "AI recommendations", STORE_SUPERVISOR: "AI recommendations" },
  },
  { path: "/transfers", icon: ArrowLeftRight, label: { SUPER_ADMIN: "Stock transfers", STORE_SUPERVISOR: "Stock transfers" } },
  { path: "/purchase-orders", icon: ClipboardList, label: { SUPER_ADMIN: "Purchase orders", STORE_SUPERVISOR: "Purchase orders" } },
  { path: "/approvals", icon: CheckCircle2, label: { SUPER_ADMIN: "Approvals", STORE_SUPERVISOR: "Approvals" } },
  { path: "/goods-receipt", icon: PackageCheck, label: { SUPER_ADMIN: null, STORE_SUPERVISOR: "Goods receipt" } },
  { path: "/analytics", icon: BarChart3, label: { SUPER_ADMIN: "Analytics", STORE_SUPERVISOR: "Store reports" } },
  { path: "/monitoring", icon: Activity, label: { SUPER_ADMIN: "System monitoring", STORE_SUPERVISOR: null } },
  { path: "/settings", icon: Settings, label: { SUPER_ADMIN: "Settings", STORE_SUPERVISOR: "Profile" } },
];

export interface VisibleNavItem {
  path: string;
  icon: LucideIcon;
  label: string;
}

export function navFor(role: Role): VisibleNavItem[] {
  return NAV_ITEMS.flatMap((item) => {
    const label = item.label[role];
    return label ? [{ path: item.path, icon: item.icon, label }] : [];
  });
}

export function canAccess(role: Role, path: string): boolean {
  if (path === "/components") return true; // design-system demo page (development aid)
  const item = NAV_ITEMS.find((n) => n.path === path);
  return item !== undefined && item.label[role] !== null;
}
