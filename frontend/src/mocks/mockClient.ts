/**
 * In-browser implementation of ApiClient over the fixtures. It applies the same rules the Phase 6 API must:
 * server-side paging/sorting/search (PageParams) and store scoping — a Store Supervisor only sees their own
 * store, other stores only as name + quantity (CLAUDE.md rule 10), and asking for another store gives 403.
 */
import { ApiError, type ApiClient } from "../api/client";
import type {
  Page,
  PageQuery,
  PurchaseOrderDTO,
  RecommendationDetailDTO,
} from "../api/types";
import {
  CROSS_STORE_EVIDENCE_ADMIN,
  CROSS_STORE_TRANSFER_REC,
  LATEST_RUN,
  MOCK_PASSWORD,
  PURCHASE_ORDERS,
  RECOMMENDATIONS,
  STORES,
  TRANSFERS,
  USERS,
  dashboard,
  inventoryRows,
  storeRef,
  type MockUser,
} from "./fixtures";

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

/** Apply PageParams (page, page_size, sort, q) to an in-memory list. */
export function applyPage<T>(items: T[], query: PageQuery, searchText: (item: T) => string): Page<T> {
  const q = query.q?.trim().toLowerCase();
  let rows = q ? items.filter((item) => searchText(item).toLowerCase().includes(q)) : [...items];
  if (query.sort) {
    const desc = query.sort.startsWith("-");
    const field = desc ? query.sort.slice(1) : query.sort;
    rows = rows.sort((a, b) => {
      const va = sortValue(a, field);
      const vb = sortValue(b, field);
      const na = typeof va === "string" && va !== "" && !Number.isNaN(Number(va)) ? Number(va) : va;
      const nb = typeof vb === "string" && vb !== "" && !Number.isNaN(Number(vb)) ? Number(vb) : vb;
      const order = (na ?? "") < (nb ?? "") ? -1 : (na ?? "") > (nb ?? "") ? 1 : 0;
      return desc ? -order : order;
    });
  }
  const page = query.page ?? 1;
  const size = query.page_size ?? 25;
  return { items: rows.slice((page - 1) * size, page * size), total: rows.length, page, page_size: size };
}

export function createMockClient(getToken: () => string | null, delayMs = 120): ApiClient {
  const wait = () => new Promise<void>((resolve) => setTimeout(resolve, delayMs));

  function currentUser(): MockUser {
    const token = getToken();
    const user = USERS.find((u) => token === `${TOKEN_PREFIX}${u.username}`);
    if (!user) throw new ApiError(401, "UNAUTHORIZED", "Not authenticated");
    return user;
  }

  /** The store a request may see: a supervisor is pinned to their own store. */
  function scopeStore(requested: string | null | undefined): string | null {
    const user = currentUser();
    if (user.role === "SUPER_ADMIN") return requested ?? null;
    const own = user.store?.store_id ?? null;
    if (requested && requested !== own) throw new ApiError(403, "FORBIDDEN", "You can only view your own store");
    return own;
  }

  const isAdmin = () => currentUser().role === "SUPER_ADMIN";

  function scopePurchaseOrder(po: PurchaseOrderDTO, store: string | null): PurchaseOrderDTO {
    if (store === null) return po;
    const own = po.lines.filter((l) => l.store.store_id === store);
    const others = new Map<string, { store: (typeof po.lines)[number]["store"]; qty: number }>();
    for (const line of po.lines.filter((l) => l.store.store_id !== store)) {
      const entry = others.get(line.store.store_id) ?? { store: line.store, qty: 0 };
      entry.qty += line.qty;
      others.set(line.store.store_id, entry);
    }
    return { ...po, lines: own, other_store_lines: [...others.values()] };
  }

  return {
    async login({ username, password }) {
      await wait();
      const user = USERS.find((u) => u.username === username);
      if (!user || password !== MOCK_PASSWORD) throw new ApiError(401, "UNAUTHORIZED", "Wrong username or password");
      return { access_token: `${TOKEN_PREFIX}${user.username}`, token_type: "bearer", expires_in: 28_800 };
    },
    async getMe() {
      await wait();
      const user = currentUser();
      return {
        user_id: user.user_id,
        name: user.name,
        role: user.role,
        store: user.store ? storeRef(user.store) : null,
      };
    },
    async listStores() {
      await wait();
      const store = scopeStore(null);
      return store ? STORES.filter((s) => s.store_id === store) : STORES;
    },
    async getLatestRun() {
      await wait();
      currentUser();
      return LATEST_RUN;
    },
    async getDashboard(query) {
      await wait();
      const store = scopeStore(query.store_id);
      return dashboard(STORES.find((s) => s.store_id === store) ?? null, query.period ?? "LAST_28_DAYS");
    },
    async listRecommendations(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const rows = RECOMMENDATIONS.filter(
        (r) =>
          (store === null || r.store.store_id === store) &&
          (!query.status || r.status === query.status) &&
          (!query.type || r.rec_type === query.type),
      );
      return applyPage(rows, query, (r) => `${r.product.name} ${r.product.sku} ${r.store.name}`);
    },
    async getRecommendation(recId): Promise<RecommendationDetailDTO> {
      await wait();
      const rec = RECOMMENDATIONS.find((r) => r.rec_id === recId);
      if (!rec) throw new ApiError(404, "NOT_FOUND", "Recommendation not found");
      scopeStore(rec.store.store_id);
      const evidence =
        rec.rec_id === CROSS_STORE_TRANSFER_REC.rec_id
          ? isAdmin()
            ? CROSS_STORE_EVIDENCE_ADMIN
            : { ...CROSS_STORE_EVIDENCE_ADMIN, donor_surplus: null, donor_protected_requirement: null }
          : null;
      return { recommendation: rec, evidence, reason: evidence ? "PARTIAL_SURPLUS" : null };
    },
    async getStoreInventory(storeId, query) {
      await wait();
      scopeStore(storeId);
      const index = STORES.findIndex((s) => s.store_id === storeId);
      if (index < 0) throw new ApiError(404, "NOT_FOUND", "Store not found");
      const rows = inventoryRows(index).filter(
        (r) => (!query.category || r.product.category === query.category) && (!query.risk || r.stockout_risk === query.risk),
      );
      return applyPage(rows, query, (r) => `${r.product.name} ${r.product.sku}`);
    },
    async listTransfers(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const rows = TRANSFERS.filter(
        (t) =>
          (store === null || t.from_store.store_id === store || t.to_store.store_id === store) &&
          (!query.status || t.status === query.status),
      );
      return applyPage(rows, query, (t) => `${t.product.name} ${t.from_store.name} ${t.to_store.name}`);
    },
    async listPurchaseOrders(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const rows = PURCHASE_ORDERS.filter(
        (po) =>
          (store === null || po.lines.some((l) => l.store.store_id === store)) &&
          (!query.status || po.status === query.status),
      ).map((po) => scopePurchaseOrder(po, store));
      return applyPage(rows, query, (po) => po.supplier.name);
    },
  };
}
