/** Dashboards (D-46): every figure comes from the API (here: fixtures computed from the synthetic data). */
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { formatINRCompact, formatNumber } from "../lib/format";
import { FIXTURES } from "../mocks/fixtures";
import { renderApp } from "./render";

const store = (code: string) => FIXTURES.stores.find((s) => s.code === code)!;

describe("Dashboard", () => {
  it("Super Admin, all stores: KPIs, store performance and widgets come from the API data", async () => {
    renderApp("/", "admin");
    expect(await screen.findByRole("heading", { name: "Business Overview" })).toBeTruthy();
    const summary = FIXTURES.dashboard.all!;
    const insights = FIXTURES.dashboard_insights.all!;
    const revenue = await screen.findByRole("region", { name: "Revenue" });
    expect(within(revenue).getByText(formatINRCompact(summary.revenue))).toBeTruthy();
    const risk = screen.getByRole("region", { name: "High stock-out risk" });
    expect(within(risk).getByText(formatNumber(insights.stock_health.high_risk))).toBeTruthy();
    const perf = await screen.findByRole("region", { name: "Store performance" });
    for (const s of FIXTURES.stores) expect(within(perf).getByText(s.name)).toBeTruthy();
    expect(screen.queryByText(/42\.8L|Anna Nagar|L2 Super Admin/)).toBeNull(); // no sample figures, no role switch
  });

  it("Store Supervisor sees only their store, no store comparison and no role switcher", async () => {
    renderApp("/", "sup.c");
    expect(await screen.findByRole("heading", { name: "Store Dashboard" })).toBeTruthy();
    expect((await screen.findAllByText(new RegExp(store("C").name))).length).toBeGreaterThan(0);
    const summary = FIXTURES.dashboard[store("C").store_id]!;
    const value = await screen.findByRole("region", { name: "Inventory value" });
    expect(within(value).getByText(formatINRCompact(summary.inventory_value))).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Store performance" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Super Admin/ })).toBeNull();
    expect(await screen.findByRole("region", { name: "Fast and slow movers" })).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderApp("/", "admin");
    await screen.findByRole("region", { name: "Store performance" });
    expect(await axe(container)).toHaveNoViolations();
  });
});
