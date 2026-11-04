import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { CROSS_STORE_TRANSFER_REC, PURCHASE_ORDERS, STORES } from "./fixtures";
import { applyPage, createMockClient } from "./mockClient";

const as = (username: string | null) => createMockClient(() => (username ? `mock-token:${username}` : null), 0);
const [STORE_A, , STORE_C] = STORES;

describe("mock API — store scoping (CLAUDE.md rule 10)", () => {
  it("requires sign-in", async () => {
    await expect(as(null).getMe()).rejects.toMatchObject({ status: 401 });
  });

  it("logs in with the demo password only", async () => {
    await expect(as(null).login({ username: "sup.a", password: "demo" })).resolves.toMatchObject({ token_type: "bearer" });
    await expect(as(null).login({ username: "sup.a", password: "nope" })).rejects.toBeInstanceOf(ApiError);
  });

  it("pins a supervisor to their own store and forbids others", async () => {
    const supA = as("sup.a");
    const page = await supA.listRecommendations({ page: 1, page_size: 200 });
    expect(page.items.every((r) => r.store.store_id === STORE_A?.store_id)).toBe(true);
    await expect(supA.getStoreInventory(STORE_C!.store_id, {})).rejects.toMatchObject({ status: 403, code: "FORBIDDEN" });
    await expect(supA.listStores()).resolves.toHaveLength(1);
  });

  it("scopes transfer evidence per viewer (D-32)", async () => {
    const destination = await as("sup.c").getRecommendation(CROSS_STORE_TRANSFER_REC.rec_id);
    const donor = await as("sup.a").getRecommendation(CROSS_STORE_TRANSFER_REC.rec_id);
    const admin = await as("admin").getRecommendation(CROSS_STORE_TRANSFER_REC.rec_id);

    // destination supervisor: donor as name + quantity, plus a numberless assurance
    expect(destination.recommendation.counterpart).toEqual({ store: { store_id: STORE_A!.store_id, name: STORE_A!.name }, qty: 24 });
    expect(destination.evidence?.donor_surplus).toBeNull();
    expect(destination.evidence?.donor_protected_requirement).toBeNull();
    expect(destination.evidence?.donor_keeps_requirement).toBe(true);
    // donor supervisor: it is their own stock — surplus and protected requirement are shown
    expect(donor.evidence?.donor_surplus).toBe(24);
    expect(donor.evidence?.donor_protected_requirement).toBe(30);
    // super admin: everything
    expect(admin.evidence?.donor_surplus).toBe(24);
    expect(admin.evidence?.donor_protected_requirement).toBe(30);
  });

  it("forbids a supervisor of an uninvolved store from opening the transfer", async () => {
    await expect(as("sup.b").getRecommendation(CROSS_STORE_TRANSFER_REC.rec_id)).rejects.toMatchObject({ status: 403 });
  });

  it("reduces other stores' PO lines to name + quantity for a supervisor", async () => {
    const page = await as("sup.b").listPurchaseOrders({});
    const po = page.items[0]!;
    expect(po.lines.map((l) => l.store.name)).toEqual(["Store B - College area"]);
    expect((po.other_store_lines ?? []).map((c) => [c.store.name, c.qty])).toEqual([
      ["Store A - Residential", 35],
      ["Store C - Temple street", 51],
    ]);
    const admin = await as("admin").listPurchaseOrders({});
    expect(admin.items[0]!.lines).toHaveLength(PURCHASE_ORDERS[0]!.lines.length);
  });

  it("shows a supervisor only transfers that involve their store", async () => {
    const supB = await as("sup.b").listTransfers({});
    const storeB = STORES[1]!.store_id;
    expect(supB.items.length).toBeGreaterThan(0);
    expect(supB.items.every((t) => t.from_store.store_id === storeB || t.to_store.store_id === storeB)).toBe(true);
  });
});

describe("applyPage — server-side paging contract", () => {
  const rows = [5, 3, 9, 1, 7].map((n) => ({ id: `r${n}`, qty: n, product: { name: `Item ${n}` } }));

  it("pages, sorts (incl. descending) and searches", () => {
    expect(applyPage(rows, { page: 2, page_size: 2, sort: "qty" }, (r) => r.product.name)).toMatchObject({
      items: [{ qty: 5 }, { qty: 7 }],
      total: 5,
      page: 2,
      page_size: 2,
    });
    expect(applyPage(rows, { sort: "-qty" }, (r) => r.product.name).items[0]?.qty).toBe(9);
    expect(applyPage(rows, { sort: "name" }, (r) => r.product.name).items[0]?.qty).toBe(1);
    expect(applyPage(rows, { q: "item 7" }, (r) => r.product.name).total).toBe(1);
  });

  it("sorts priority and stockout risk by rank, not alphabetically", () => {
    const recs = [{ priority: "NORMAL" }, { priority: "HIGH" }, { priority: "NORMAL" }];
    expect(applyPage(recs, { sort: "-priority" }, () => "").items[0]?.priority).toBe("HIGH");
    const risks = [{ stockout_risk: "LOW" }, { stockout_risk: "HIGH" }, { stockout_risk: "MEDIUM" }];
    expect(applyPage(risks, { sort: "-stockout_risk" }, () => "").items.map((r) => r.stockout_risk)).toEqual(["HIGH", "MEDIUM", "LOW"]);
  });
});
