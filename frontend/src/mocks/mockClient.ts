/**
 * In-browser implementation of ApiClient over the exported fixtures. It applies the rules the Phase 6 API must:
 * server-side paging/sorting/search (PageParams; priority and stockout_risk sort by rank) and per-viewer store
 * scoping (D-32): a Store Supervisor sees only their own store; another store appears as name + quantity; the
 * donor store's own supervisor may open a transfer it donates to and sees its own stock; other stores → 403.
 */
import { ApiError, type ApiClient } from "../api/client";
import type {
  CursorPage,
  Evidence,
  InventoryMovementDTO,
  Page,
  PageQuery,
  PurchaseOrderDTO,
  StoreDTO,
  StoreRef,
} from "../api/types";
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

/** Opaque movement cursor, same format as the backend (base64url JSON of the last row's sort key, D-37). */
export function encodeMovementCursor(m: Pick<InventoryMovementDTO, "occurred_at" | "movement_id">): string {
  return btoa(JSON.stringify({ t: m.occurred_at, id: m.movement_id }))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function decodeMovementCursor(token: string): { t: string; id: string } {
  try {
    const key = JSON.parse(atob(token.replaceAll("-", "+").replaceAll("_", "/"))) as { t?: unknown; id?: unknown };
    if (typeof key.t === "string" && typeof key.id === "string") return { t: key.t, id: key.id };
  } catch {
    // fall through to the 422 below
  }
  throw new ApiError(422, "VALIDATION", "Invalid cursor");
}

/** Newest first, then movement_id descending: the API order of the ledger (D-37). */
function compareMovements(a: InventoryMovementDTO, b: InventoryMovementDTO): number {
  const byTime = Date.parse(b.occurred_at) - Date.parse(a.occurred_at);
  if (byTime !== 0) return byTime;
  return a.movement_id < b.movement_id ? 1 : a.movement_id > b.movement_id ? -1 : 0;
}

/** Keyset paging over movements: rows strictly after the cursor's key, no total (D-37). */
export function applyMovementCursor(
  items: InventoryMovementDTO[],
  query: { cursor?: string | null; page_size?: number; q?: string | null },
  searchText: (item: InventoryMovementDTO) => string,
): CursorPage<InventoryMovementDTO> {
  const q = query.q?.trim().toLowerCase();
  const size = query.page_size ?? 25;
  let rows = (q ? items.filter((m) => searchText(m).toLowerCase().includes(q)) : [...items]).sort(compareMovements);
  if (query.cursor) {
    const key = decodeMovementCursor(query.cursor);
    const after = { occurred_at: key.t, movement_id: key.id } as InventoryMovementDTO;
    rows = rows.filter((m) => compareMovements(after, m) < 0); // strictly after the cursor row in API order
  }
  const pageRows = rows.slice(0, size);
  const last = pageRows.at(-1);
  const next_cursor = rows.length > size && last ? encodeMovementCursor(last) : null;
  return { items: pageRows, next_cursor, page_size: size };
}

export function createMockClient(
  getToken: () => string | null,
  delayMs = 120,
  data: MockFixtures = FIXTURES,
): ApiClient {
  const wait = () => new Promise<void>((resolve) => setTimeout(resolve, delayMs));
  const storeById = new Map(data.stores.map((s) => [s.store_id, s]));
  const rules = data.business_rules.map((r) => ({ ...r })); // editable per mock client instance
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
    async getAnalytics(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const analytics = data.analytics[store ?? "all"];
      if (!analytics) throw new ApiError(404, "NOT_FOUND", "No analytics for this store");
      return { ...analytics, period: query.period ?? "LAST_28_DAYS" };
    },
    async listBusinessRules() {
      await wait();
      if (!isAdmin()) throw new ApiError(403, "FORBIDDEN", "Super Admin only");
      return rules.map((r) => ({ ...r }));
    },
    async updateBusinessRule(key, value) {
      await wait();
      if (!isAdmin()) throw new ApiError(403, "FORBIDDEN", "Super Admin only");
      const rule = rules.find((r) => r.key === key);
      if (!rule) throw new ApiError(404, "NOT_FOUND", `Unknown business rule ${key}`);
      const n = Number(value);
      const numeric = rule.kind !== "boolean" && rule.kind !== "choice";
      if (numeric && (Number.isNaN(n) || (rule.min != null && n < rule.min) || (rule.max != null && n > rule.max)))
        throw new ApiError(422, "VALIDATION", "Invalid business rule value");
      if (rule.kind === "choice" && !rule.choices?.includes(String(value)))
        throw new ApiError(422, "VALIDATION", "Invalid business rule value");
      rule.value = rule.kind === "money" ? n.toFixed(2) : rule.kind === "decimal" ? String(value) : value;
      return { ...rule };
    },
    async getDashboardInsights(query) {
      await wait();
      const store = scopeStore(query.store_id);
      const insights = data.dashboard_insights[store ?? "all"];
      if (!insights) throw new ApiError(404, "NOT_FOUND", "No dashboard for this store");
      return { ...insights, period: query.period ?? "LAST_28_DAYS" };
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
          (!query.from || m.business_date >= query.from) &&
          (!query.to || m.business_date <= query.to),
      );
      return applyMovementCursor(rows, query, productText);
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
    async getPurchaseOrder(poId) {
      await wait();
      const po = data.purchase_orders.find((p) => p.po_id === poId);
      if (!po) throw new ApiError(404, "NOT_FOUND", "Purchase order not found");
      const user = currentUser();
      return scopePurchaseOrder(po, user.role === "STORE_SUPERVISOR" ? user.store_id : null);
    },
    async createApproval(body) {
      await wait();
      return {
        po_id: body.entity_id,
        status: body.decision === "APPROVED" ? "APPROVED" : "REJECTED",
        approval_id: "00000000-0000-0000-0000-000000000001",
      };
    },
    async getTransfer(transferId) {
      await wait();
      const t = data.transfers.find((tr) => tr.transfer_id === transferId);
      if (!t) throw new ApiError(404, "NOT_FOUND", "Transfer not found");
      return t;
    },
    async acceptTransfer(transferId) {
      await wait();
      const t = data.transfers.find((tr) => tr.transfer_id === transferId);
      if (!t) throw new ApiError(404, "NOT_FOUND", "Transfer not found");
      t.status = "DEST_ACCEPTED";
      return t;
    },
    async approveReleaseTransfer(transferId) {
      await wait();
      const t = data.transfers.find((tr) => tr.transfer_id === transferId);
      if (!t) throw new ApiError(404, "NOT_FOUND", "Transfer not found");
      t.status = "DONOR_APPROVED";
      return t;
    },
    async rejectTransfer(transferId) {
      await wait();
      const t = data.transfers.find((tr) => tr.transfer_id === transferId);
      if (!t) throw new ApiError(404, "NOT_FOUND", "Transfer not found");
      t.status = "REJECTED";
      return t;
    },
    async dispatchTransfer(transferId) {
      await wait();
      const t = data.transfers.find((tr) => tr.transfer_id === transferId);
      if (!t) throw new ApiError(404, "NOT_FOUND", "Transfer not found");
      t.status = "DISPATCHED";
      return t;
    },
    async receiveTransfer(transferId, receivedQty) {
      await wait();
      const t = data.transfers.find((tr) => tr.transfer_id === transferId);
      if (!t) throw new ApiError(404, "NOT_FOUND", "Transfer not found");
      t.status = "RECEIVED";
      t.received_qty = receivedQty;
      return t;
    },
    async receiveGoods(poId) {
      await wait();
      const po = data.purchase_orders.find((p) => p.po_id === poId);
      if (!po) throw new ApiError(404, "NOT_FOUND", "Purchase order not found");
      po.status = "RECEIVED";
      return po;
    },
    async resolvePurchaseOrder(poId, body) {
      await wait();
      const po = data.purchase_orders.find((p) => p.po_id === poId);
      if (!po) throw new ApiError(404, "NOT_FOUND", "Purchase order not found");
      po.status = body.decision === "APPROVE" ? "PENDING_L1" : "REJECTED";
      return po;
    },
    async closeShortPurchaseOrder(poId) {
      await wait();
      const po = data.purchase_orders.find((p) => p.po_id === poId);
      if (!po) throw new ApiError(404, "NOT_FOUND", "Purchase order not found");
      po.status = "RECEIVED";
      return po;
    },
    async actOnRecommendation(recId, body) {
      await wait();
      const rec = data.recommendations.find((r) => r.rec_id === recId);
      if (!rec) throw new ApiError(404, "NOT_FOUND", "Recommendation not found");
      rec.status = body.action === "ACCEPT" ? "ACCEPTED" : body.action === "REJECT" ? "REJECTED" : "EDITED";
      return rec;
    },
    async listNotifications() {
      await wait();
      return [];
    },
    async markNotificationRead(id) {
      await wait();
      return {
        notification_id: id,
        message: "Read",
        read_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      };
    },
    async listAgentRuns() {
      await wait();
      return [];
    },
    async getAgentRun(runId) {
      await wait();
      return {
        run_id: runId,
        parent_run_id: null,
        agent_name: "nightly_orchestrator",
        run_date: new Date().toISOString().slice(0, 10),
        status: "SUCCESS",
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        input_ref: {},
        output_summary: "Completed successfully",
        error: null,
        tool_calls: [],
        llm_usages: [],
      };
    },
    async triggerNightlyRun() {
      await wait();
      return {
        message: "Nightly run triggered",
        run_date: new Date().toISOString().slice(0, 10),
      };
    },
  };
}
