import { describe, expect, it } from "vitest";

import { canAccess, navFor } from "./nav";

describe("role-based navigation (design doc §5)", () => {
  it("hides admin-only items from store supervisors", () => {
    const labels = navFor("STORE_SUPERVISOR").map((i) => i.label);
    expect(labels).toContain("Store overview");
    expect(labels).toContain("Goods receipt");
    expect(labels).not.toContain("Stores");
    expect(labels).not.toContain("System monitoring");
  });

  it("hides supervisor-only items from the super admin", () => {
    const labels = navFor("SUPER_ADMIN").map((i) => i.label);
    expect(labels).toContain("Business overview");
    expect(labels).toContain("System monitoring");
    expect(labels).not.toContain("Goods receipt");
  });

  it("guards routes the same way", () => {
    expect(canAccess("STORE_SUPERVISOR", "/monitoring")).toBe(false);
    expect(canAccess("SUPER_ADMIN", "/goods-receipt")).toBe(false);
    expect(canAccess("STORE_SUPERVISOR", "/components")).toBe(true);
  });
});
