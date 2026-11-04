/**
 * In-browser implementation of ApiClient over the exported fixtures. It applies the rules the Phase 6 API must:
 * server-side paging/sorting/search (PageParams; priority and stockout_risk sort by rank) and per-viewer store
 * scoping (D-32): a Store Supervisor sees only their own store; another store appears as name + quantity; the
 * donor store's own supervisor may open a transfer it donates to and sees its own stock; other stores → 403.
 */
import { ApiError, type ApiClient } from "../api/client";
import type { Evidence, Page, PageQuery, PurchaseOrderDTO, StoreDTO, StoreRef } from "../api/types";
import { FIXTURES, MOCK_PASSWORD, type MockFixtures, type MockUser } from "./fixtures";

const TOKEN_PREFIX = "mock-token:";

/** Fields sorted by business rank instead of alphabetically (the Phase 6 API must do the same, D-32). */
const RANKS: Record<string, Record<string, number>> = {
  priority: { NORMAL: 1, HIGH: 2 },
  stockout_risk: { LOW: 1, MEDIUM: 2, HIGH: 3 },
};

function sortValue(item: unknown, field: string): unknown {
  const record = item as Record<string, unknown>;
  const rank = RANKS[field];
  if (rank && typeof record[field] === "string") return rank[record[field] as string] ?? 0;
  if (field in record) return record[field];
  const nested = record.product as Record<string, unknown> | undefined; // e.g. sort=name → product.name
  return nested?.[field];
}

function comparable(value: unknown): number | string {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value !== "" && !Number.isNaN(Number(value))) return Number(value);
  if (typeof value === "boolean") return value ? 1 : 0;
  return typeof value === "string" ? value : "";
}

/** Apply PageParams (page, page_size, sort, q) to an in-memory list. */
export function applyPage<T>(items: T[], query: PageQuery, searchText: (item: T) => string): Page<T> {
  const q = query.q?.trim().toLowerCase();
  let rows = q ? items.filter((item) => searchText(item).toLowerCase().includes(q)) : [...items];
  if (query.sort) {
    const desc = query.sort.startsWith("-");
    const field = desc ? query.sort.slice(1) : query.sort;
    rows = rows.sort((a, b) => {
      const va = comparable(sortValue(a, field));
      const vb = comparable(sortValue(b, field));
      const order = va < vb ? -1 : va > vb ? 1 : 0;
      return desc ? -order : order;
    });
  }
  const page = query.page ?? 1;
  const size = query.page_size ?? 25;
  return { items: rows.slice((page - 1) * size, page * size), total: rows.length, page, page_size: size };
}

export function createMockClient(
  getToken: () => string | null,
  delayMs = 120,
  data: MockFixtures = FIXTURES,
): ApiClient {
  const wait = () => new Promise<void>((resolve) => setTimeout(resolve, delayMs));
  const storeById = new Map(data.stores.map((s) => [s.store_id, s]));
  const ref = (s: StoreDTO): StoreRef => ({ store_id: s.store_id, name: s.name });

  function currentUser(): MockUser {
    const token = getToken();
    const user = data.users.find((u) => token === `${TOKEN_PREFIX}${u.username}`);
    if (!user) throw new ApiError(401, "UNAUTHORIZED", "Not authenticated");
    return user;
  }

  const isAdmin = () => currentUser().role === "SUPER_ADMIN";

  /** The store a request may see: a supervisor is pinned to their own store. */
  function scopeStore(requested: string | null | undefined): string | null {
    const user = currentUser();
    if (user.role === "SUPER_ADMIN") return requested ?? null;
    if (requested && requested !== user.store_id) {
      throw new ApiError(403, "FORBIDDEN", "You can only view your own store");
    }
    return user.store_id;
  }

  function storeOrThrow(storeId: string): StoreDTO {
    scopeStore(storeId);
    const store = storeById.get(storeId);
    if (!store) throw new ApiError(404, "NOT_FOUND", "Store not found");
    return store;
  }

  function scopePurchaseOrder(po: PurchaseOrderDTO, store: string | null): PurchaseOrderDTO {
    if (store === null) return po;
    const own = po.lines.filter((l) => l.store.store_id === store);
    const others = new Map<string, { store: StoreRef; qty: number }>();
    for (const line of po.lines.filter((l) => l.store.store_id !== store)) {
      const entry = others.get(line.store.store_id) ?? { store: line.store, qty: 0 };
      entry.qty += line.qty;
      others.set(line.store.store_id, entry);
    }
    return { ...po, lines: own, other_store_lines: [...others.values()] };
  }

  const productText = (p: { product: { name: string; sku: string } }) => `${p.product.name} ${p.product.sku}`;

  return {
    async login({ username, password }) {
      await wait();
      const user = data.users.find((u) => u.username === username);
      if (!user || password !== MOCK_PASSWORD) throw new ApiError(401, "UNAUTHORIZED", "Wrong username or password");
      return { access_token: `${TOKEN_PREFIX}${user.username}`, token_type: "bearer", expires_in: 28_800 };
    },
    async getMe() {
      await wait();
      const user = currentUser();
      const store = user.store_id ? storeById.get(user.store_id) : undefined;
      return { user_id: user.user_id, name: user.name, role: user.role, store: store ? ref(store) : null };
    },
    async listStores() {
      await wait();
      const store = scopeStore(null);
      return store ? data.stores.filter((s) => s.store_id === store) : data.stores;
    },
    async getLatestRun() {
      await wait();
      currentUser();
      return data.latest_run;
    },
    async getDashboard(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const summary = data.dashboard[store ?? "all"];
      if (!summary) throw new ApiError(404, "NOT_FOUND", "No dashboard for this store");
      return { ...summary, period: query.period ?? "LAST_28_DAYS" };
    },
    async listRecommendations(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const rows = data.recommendations.filter(
        (r) =>
          (store === null || r.store.store_id === store) &&
          (!query.status || r.status === query.status) &&
          (!query.type || r.rec_type === query.type) &&
          (!query.priority || r.priority === query.priority) &&
          (!query.product_id || r.product.product_id === query.product_id),
      );
      return applyPage(rows, query, (r) => `${productText(r)} ${r.store.name}`);
    },
    async getRecommendation(recId) {
      await wait();
      const rec = data.recommendations.find((r) => r.rec_id === recId);
      if (!rec) throw new ApiError(404, "NOT_FOUND", "Recommendation not found");
      const user = currentUser();
      const isDonorViewer = rec.rec_type === "TRANSFER" && rec.counterpart?.store.store_id === user.store_id;
      if (!isDonorViewer) scopeStore(rec.store.store_id); // the store's own recommendation, or 403
      const full = data.evidence[recId] ?? null;
      let evidence: Evidence | null = full;
      if (full?.kind === "TRANSFER" && !isAdmin() && !isDonorViewer) {
        // destination supervisor: donor as name + quantity and the numberless assurance only (D-32)
        evidence = { ...full, donor_surplus: null, donor_protected_requirement: null };
      }
      return { recommendation: rec, evidence };
    },
    async getStoreInventory(storeId, query) {
      await wait();
      const store = storeOrThrow(storeId);
      const all = data.inventory[storeId] ?? [];
      const rows = all.filter(
        (r) =>
          (!query.category || r.product.category === query.category) &&
          (!query.risk || r.stockout_risk === query.risk) &&
          (!query.refill_only || r.refill_from_backroom),
      );
      return {
        ...applyPage(rows, query, productText),
        store: ref(store),
        summary: {
          products: all.length,
          high_risk: all.filter((r) => r.stockout_risk === "HIGH").length,
          medium_risk: all.filter((r) => r.stockout_risk === "MEDIUM").length,
          refill_needed: all.filter((r) => r.refill_from_backroom).length,
          near_expiry_qty: all.reduce((sum, r) => sum + r.near_expiry_qty, 0),
          shortage_products: all.filter((r) => r.surplus_or_shortage < 0).length,
        },
      };
    },
    async listStoreMovements(storeId, query) {
      await wait();
      storeOrThrow(storeId);
      const rows = (data.movements[storeId] ?? []).filter(
        (m) =>
          (!query.product_id || m.product.product_id === query.product_id) &&
          (!query.type || m.movement_type === query.type) &&
          (!query.from || m.created_at.slice(0, 10) >= query.from) &&
          (!query.to || m.created_at.slice(0, 10) <= query.to),
      );
      return applyPage(rows, query, productText);
    },
    async listStoreBatches(storeId, query) {
      await wait();
      storeOrThrow(storeId);
      const rows = (data.batches[storeId] ?? []).filter(
        (b) => !query.product_id || b.product.product_id === query.product_id,
      );
      return applyPage(rows, query, (b) => `${productText(b)} ${b.batch_no}`);
    },
    async listStoreExpiring(storeId, query) {
      await wait();
      storeOrThrow(storeId);
      const within = query.within_days ?? 14;
      const rows = (data.batches[storeId] ?? []).filter((b) => b.days_left <= within);
      return applyPage(rows, query, (b) => `${productText(b)} ${b.batch_no}`);
    },
    async listTransfers(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const rows = data.transfers.filter(
        (t) =>
          (store === null || t.from_store.store_id === store || t.to_store.store_id === store) &&
          (!query.status || t.status === query.status) &&
          (!query.product_id || t.product.product_id === query.product_id),
      );
      return applyPage(rows, query, (t) => `${productText(t)} ${t.from_store.name} ${t.to_store.name}`);
    },
    async listPurchaseOrders(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const rows = data.purchase_orders
        .filter(
          (po) =>
            (store === null || po.lines.some((l) => l.store.store_id === store)) &&
            (!query.status || po.status === query.status),
        )
        .map((po) => scopePurchaseOrder(po, store));
      return applyPage(rows, query, (po) => po.supplier.name);
    },
  };
}
