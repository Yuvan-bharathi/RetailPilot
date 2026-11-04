import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { RecommendationDTO, StoreDTO } from "../api/types";
import { FIXTURES } from "./fixtures";
import { applyPage, createMockClient } from "./mockClient";

const as = (username: string | null) => createMockClient(() => (username ? `mock-token:${username}` : null), 0);
const store = (code: string): StoreDTO => FIXTURES.stores.find((s) => s.code === code)!;
const scenarioRec = (n: "1" | "2" | "3" | "4" | "5", type: RecommendationDTO["rec_type"]): RecommendationDTO =>
  FIXTURES.recommendations.find((r) => FIXTURES.scenarios[n].rec_ids.includes(r.rec_id) && r.rec_type === type)!;

describe("fixtures exported from the synthetic data (real Phase 3 tools)", () => {
  it("contain the five demo scenarios with their planted numbers", () => {
    expect(scenarioRec("3", "TRANSFER")).toMatchObject({ qty: 24, store: { name: store("C").name } });
    expect(scenarioRec("3", "TRANSFER").counterpart).toEqual({
      store: { store_id: store("A").store_id, name: store("A").name },
      qty: 24,
    });
    expect(scenarioRec("3", "REORDER").qty).toBe(16);
    expect(scenarioRec("2", "TRANSFER").qty).toBe(20);
    expect(scenarioRec("4", "CO_REPLENISH").qty).toBe(3);
    expect(scenarioRec("5", "TRANSFER").qty).toBe(30);
    expect(FIXTURES.scenarios["1"].rec_ids).toHaveLength(3);
  });
});

describe("mock API — per-viewer scoping (D-32)", () => {
  it("requires sign-in and the demo password", async () => {
    await expect(as(null).getMe()).rejects.toMatchObject({ status: 401 });
    await expect(as(null).login({ username: "sup.a", password: "demo" })).resolves.toMatchObject({
      token_type: "bearer",
    });
    await expect(as(null).login({ username: "sup.a", password: "nope" })).rejects.toBeInstanceOf(ApiError);
  });

  it("pins a supervisor to their own store and forbids others", async () => {
    const supA = as("sup.a");
    const page = await supA.listRecommendations({ page: 1, page_size: 200 });
    expect(page.total).toBeGreaterThan(0);
    expect(page.items.every((r) => r.store.store_id === store("A").store_id)).toBe(true);
    await expect(supA.getStoreInventory(store("C").store_id, {})).rejects.toMatchObject({ status: 403, code: "FORBIDDEN" });
    await expect(supA.listStoreMovements(store("B").store_id, {})).rejects.toMatchObject({ status: 403 });
    await expect(supA.listStores()).resolves.toHaveLength(1);
  });

  it("scopes transfer evidence per viewer", async () => {
    const recId = scenarioRec("3", "TRANSFER").rec_id;
    const destination = (await as("sup.c").getRecommendation(recId)).evidence;
    const donor = (await as("sup.a").getRecommendation(recId)).evidence;
    const admin = (await as("admin").getRecommendation(recId)).evidence;
    if (destination?.kind !== "TRANSFER" || donor?.kind !== "TRANSFER" || admin?.kind !== "TRANSFER") {
      throw new Error("expected transfer evidence for every viewer");
    }

    expect(destination.donor_surplus).toBeNull();
    expect(destination.donor_protected_requirement).toBeNull();
    expect(destination.donor_keeps_requirement).toBe(true);
    expect(donor.donor_surplus).toBe(24);
    expect(donor.donor_protected_requirement).toBe(30);
    expect(admin.donor_surplus).toBe(24);
    await expect(as("sup.b").getRecommendation(recId)).rejects.toMatchObject({ status: 403 });
  });

  it("returns typed evidence of the matching kind", async () => {
    const reorder = await as("sup.c").getRecommendation(scenarioRec("3", "REORDER").rec_id);
    expect(reorder.evidence).toMatchObject({ kind: "REORDER", reason: "PARTIAL_SURPLUS", transferred_qty: 24 });
    const co = (await as("sup.a").getRecommendation(scenarioRec("4", "CO_REPLENISH").rec_id)).evidence;
    expect(co?.kind).toBe("CO_REPLENISH");
    if (co?.kind === "CO_REPLENISH") expect(co.lift).toBeGreaterThanOrEqual(1.5);
    const expiry = await as("admin").getRecommendation(scenarioRec("5", "TRANSFER").rec_id);
    expect(expiry.evidence).toMatchObject({ kind: "TRANSFER", expiring_batch: { days_left: 5, at_risk_qty: 30 } });
  });

  it("reduces other stores' PO lines to name + quantity for a supervisor", async () => {
    const admin = await as("admin").listPurchaseOrders({ page_size: 200 });
    const rice = admin.items.find((po) => po.lines.some((l) => l.product.name.startsWith("Rice 5 kg")))!;
    expect(rice.lines).toHaveLength(3); // scenario 1: one consolidated PO, a line per store

    const supB = await as("sup.b").listPurchaseOrders({ page_size: 200 });
    const scoped = supB.items.find((po) => po.po_id === rice.po_id)!;
    expect(scoped.lines.map((l) => l.store.name)).toEqual([store("B").name]);
    expect((scoped.other_store_lines ?? []).map((c) => c.store.name).sort()).toEqual(
      [store("A").name, store("C").name].sort(),
    );
  });

  it("shows a supervisor only transfers that involve their store", async () => {
    const supB = await as("sup.b").listTransfers({ page_size: 200 });
    const id = store("B").store_id;
    expect(supB.items.every((t) => t.from_store.store_id === id || t.to_store.store_id === id)).toBe(true);
  });
});

describe("mock API — inventory endpoints", () => {
  it("returns inventory with store-wide summary counts and filters", async () => {
    const admin = as("admin");
    const all = await admin.getStoreInventory(store("C").store_id, { page_size: 200 });
    expect(all.store.name).toBe(store("C").name);
    expect(all.summary.products).toBe(all.total);
    expect(all.summary.high_risk).toBe(all.items.filter((r) => r.stockout_risk === "HIGH").length);

    const high = await admin.getStoreInventory(store("C").store_id, { risk: "HIGH", page_size: 200 });
    expect(high.items.every((r) => r.stockout_risk === "HIGH")).toBe(true);
    expect(high.summary.products).toBe(all.summary.products); // the summary covers the whole store

    const refill = await admin.getStoreInventory(store("C").store_id, { refill_only: true, page_size: 200 });
    expect(refill.items.every((r) => r.refill_from_backroom)).toBe(true);
  });

  it("filters the movement ledger by type and shows the planted reconciliation adjustment", async () => {
    const admin = as("admin");
    const sales = await admin.listStoreMovements(store("A").store_id, { type: "SALE", page_size: 50 });
    expect(sales.items.every((m) => m.movement_type === "SALE" && m.qty < 0)).toBe(true);
    const adjustments = await admin.listStoreMovements(store("B").store_id, { type: "ADJUSTMENT" });
    expect(adjustments.items.map((m) => m.qty)).toEqual([-3]);
  });

  it("pages the ledger by cursor, newest first, without gaps, overlaps or a total (D-37)", async () => {
    const admin = as("admin");
    const storeId = store("A").store_id;
    const all = FIXTURES.movements[storeId]!;
    const seen: string[] = [];
    let cursor: string | undefined;
    let pages = 0;
    do {
      const page = await admin.listStoreMovements(storeId, { cursor, page_size: 40 });
      expect(page).not.toHaveProperty("total");
      expect(page.items.length).toBeLessThanOrEqual(40);
      seen.push(...page.items.map((m) => m.movement_id));
      cursor = page.next_cursor ?? undefined;
      pages += 1;
    } while (cursor);
    expect(pages).toBeGreaterThan(1);
    expect(seen).toEqual(all.map((m) => m.movement_id)); // fixture order is the API order
    const times = all.map((m) => Date.parse(m.occurred_at));
    expect(times.every((t, i) => i === 0 || t <= times[i - 1]!)).toBe(true);
  });

  it("filters the ledger by business date and rejects a malformed cursor", async () => {
    const admin = as("admin");
    const day = FIXTURES.movements[store("A").store_id]![0]!.business_date;
    const page = await admin.listStoreMovements(store("A").store_id, { from: day, to: day, page_size: 200 });
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.items.every((m) => m.business_date === day)).toBe(true);
    await expect(admin.listStoreMovements(store("A").store_id, { cursor: "bm90IGpzb24" })).rejects.toMatchObject({
      status: 422,
    });
  });

  it("lists batches and the ones expiring soon", async () => {
    const admin = as("admin");
    const batches = await admin.listStoreBatches(store("A").store_id, { page_size: 200 });
    expect(batches.items.length).toBeGreaterThan(0);
    const expiring = await admin.listStoreExpiring(store("A").store_id, { within_days: 5, page_size: 200 });
    expect(expiring.items.every((b) => b.days_left <= 5)).toBe(true);
    expect(expiring.items.some((b) => b.at_risk_qty === 30)).toBe(true); // scenario 5 paneer batch
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
    expect(applyPage(risks, { sort: "-stockout_risk" }, () => "").items.map((r) => r.stockout_risk)).toEqual([
      "HIGH",
      "MEDIUM",
      "LOW",
    ]);
  });
});
