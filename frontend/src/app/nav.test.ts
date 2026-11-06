import { describe, expect, it } from "vitest";

import { canAccess, navFor } from "./nav";

describe("role-based navigation (design doc §5)", () => {
  it("hides admin-only items from store supervisors", () => {
    const labels = navFor("STORE_SUPERVISOR").map((i) => i.label);
    expect(labels).toContain("Store overview");
    expect(labels).toContain("Goods receipt");
    expect(labels).not.toContain("Stores");
    expect(labels).not.toContain("Overview");
    expect(labels).toContain("Ask RetailPilot");
  });

  it("hides supervisor-only items from the super admin", () => {
    const labels = navFor("SUPER_ADMIN").map((i) => i.label);
    expect(labels).toContain("Business overview");
    expect(labels).toEqual(expect.arrayContaining(["Overview", "Pipeline", "Visual flow", "Logs", "Decisions"]));
    expect(labels).not.toContain("System monitoring");
    expect(labels).not.toContain("Goods receipt");
  });

  it("guards routes the same way", () => {
    expect(canAccess("STORE_SUPERVISOR", "/agents")).toBe(false);
    expect(canAccess("STORE_SUPERVISOR", "/agents/stock_balancing")).toBe(false);
    expect(canAccess("STORE_SUPERVISOR", "/agents/logs/abc")).toBe(false);
    expect(canAccess("SUPER_ADMIN", "/agents/logs/abc")).toBe(true);
    expect(canAccess("STORE_SUPERVISOR", "/ask")).toBe(true);
    expect(canAccess("STORE_SUPERVISOR", "/recommendations/abc")).toBe(true);
    expect(canAccess("SUPER_ADMIN", "/goods-receipt")).toBe(false);
    expect(canAccess("STORE_SUPERVISOR", "/components")).toBe(true);
  });
});
