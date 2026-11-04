/** Store Inventory (2D) — read-only, SD-15 / design doc §6 (shelf vs backroom, FEFO, pending transfers). */
import { ArrowDownLeft, ArrowUpRight, PackageOpen, Store } from "lucide-react";
import { useDeferredValue, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";

import {
  useRecommendations,
  useStoreBatches,
  useStoreExpiring,
  useStoreInventory,
  useStoreMovements,
  useStores,
  useTransfers,
} from "../api/hooks";
import type {
  BatchDTO,
  InventoryMovementDTO,
  InventoryRowDTO,
  MovementType,
  StockoutRisk,
  StoreDTO,
} from "../api/types";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";
import { Button } from "../components/Button";
import { DataTable, type Column, type TableQuery } from "../components/DataTable";
import { Modal } from "../components/Modal";
import { StatusBadge, StatusPill } from "../components/StatusBadge";
import { Tabs } from "../components/Tabs";
import { formatDateIST, formatDateTimeIST, formatDays, formatNumber } from "../lib/format";
import { categoryLabel, KNOWN_CATEGORIES, MOVEMENT_LABEL, REC_TYPE_LABEL } from "../lib/labels";
import { useCursorPaging } from "../lib/useCursorPaging";

const LAST_STORE_KEY = "retailpilot.inventory.lastStore";

function readLastStore(): string | null {
  try {
    return localStorage.getItem(LAST_STORE_KEY);
  } catch {
    return null;
  }
}

function writeLastStore(id: string): void {
  try {
    localStorage.setItem(LAST_STORE_KEY, id);
  } catch {
    /* storage unavailable */
  }
}

const signed = (n: number) => (n > 0 ? `+${formatNumber(n)}` : n < 0 ? `−${formatNumber(-n)}` : "0");

// --- products tab -------------------------------------------------------------------------------------------

const PRODUCT_COLUMNS: Column<InventoryRowDTO>[] = [
  {
    id: "name",
    header: "Product",
    sortable: true,
    hideable: false,
    cell: (r) => (
      <span>
        <span className="font-medium text-ink">{r.product.name}</span>
        <span className="block text-xs text-ink-secondary">
          {r.product.sku} · {categoryLabel(r.product.category)}
        </span>
      </span>
    ),
  },
  {
    id: "shelf_qty",
    header: "Shelf",
    sortable: true,
    align: "right",
    cell: (r) => (
      <span className={r.shelf_qty < r.shelf_min ? "font-semibold text-danger" : ""}>{formatNumber(r.shelf_qty)}</span>
    ),
  },
  { id: "shelf_min", header: "Shelf min", align: "right", cell: (r) => formatNumber(r.shelf_min) },
  { id: "backroom_qty", header: "Backroom", sortable: true, align: "right", cell: (r) => formatNumber(r.backroom_qty) },
  { id: "incoming", header: "Incoming", align: "right", cell: (r) => formatNumber(r.incoming) },
  { id: "reserved", header: "Reserved", align: "right", cell: (r) => formatNumber(r.reserved) },
  { id: "available", header: "Available", sortable: true, align: "right", cell: (r) => formatNumber(r.available) },
  { id: "own_requirement", header: "Own requirement", align: "right", cell: (r) => formatNumber(r.own_requirement) },
  {
    id: "surplus_or_shortage",
    header: "Surplus / shortage",
    sortable: true,
    align: "right",
    cell: (r) => (
      <span
        className={
          r.surplus_or_shortage < 0 ? "font-semibold text-danger" : r.surplus_or_shortage > 0 ? "text-success" : ""
        }
      >
        {signed(r.surplus_or_shortage)}
      </span>
    ),
  },
  {
    id: "days_of_cover",
    header: "Days of cover",
    sortable: true,
    align: "right",
    cell: (r) => formatDays(r.days_of_cover),
  },
  {
    id: "stockout_risk",
    header: "Stockout risk",
    sortable: true,
    cell: (r) => <StatusPill status={r.stockout_risk} />,
  },
  {
    id: "near_expiry_qty",
    header: "Near expiry",
    sortable: true,
    align: "right",
    cell: (r) => (r.near_expiry_qty ? formatNumber(r.near_expiry_qty) : "—"),
  },
  {
    id: "transfers",
    header: "Pending transfers",
    cell: (r) =>
      r.pending_transfer_in || r.pending_transfer_out ? (
        <span className="inline-flex gap-3">
          {r.pending_transfer_in ? (
            <span className="inline-flex items-center gap-0.5" title="Incoming transfer">
              <ArrowDownLeft aria-hidden="true" size={14} className="text-success" />
              <span className="sr-only">In </span>
              {formatNumber(r.pending_transfer_in)}
            </span>
          ) : null}
          {r.pending_transfer_out ? (
            <span className="inline-flex items-center gap-0.5" title="Outgoing transfer">
              <ArrowUpRight aria-hidden="true" size={14} className="text-attention" />
              <span className="sr-only">Out </span>
              {formatNumber(r.pending_transfer_out)}
            </span>
          ) : null}
        </span>
      ) : (
        "—"
      ),
  },
  {
    id: "refill",
    header: "Refill",
    cell: (r) =>
      r.refill_from_backroom ? <StatusBadge tone="warning" icon={PackageOpen} label="Refill from backroom" /> : "—",
  },
];

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`h-8 rounded-full border px-3 text-sm ${
        active
          ? "border-brand bg-brand-soft font-semibold text-brand"
          : "border-border bg-surface text-ink hover:bg-elevated"
      }`}
    >
      {children}
    </button>
  );
}

function ProductsTab({ storeId, onOpen }: { storeId: string; onOpen: (row: InventoryRowDTO) => void }) {
  const [query, setQuery] = useState<TableQuery>({ page: 1, pageSize: 25, sort: "-stockout_risk" });
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [risk, setRisk] = useState<StockoutRisk | "">("");
  const [refillOnly, setRefillOnly] = useState(false);
  const q = useDeferredValue(search);
  const result = useStoreInventory(storeId, {
    page: query.page,
    page_size: query.pageSize,
    sort: query.sort,
    q: q || undefined,
    category: category || undefined,
    risk: risk || undefined,
    refill_only: refillOnly || undefined,
  });
  const summary = result.data?.summary;
  const reset = (fn: () => void) => {
    fn();
    setQuery((prev) => ({ ...prev, page: 1 }));
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" aria-label="Summary">
        {summary ? (
          <>
            <Chip active={risk === "HIGH"} onClick={() => reset(() => setRisk(risk === "HIGH" ? "" : "HIGH"))}>
              High stockout risk · {summary.high_risk}
            </Chip>
            <Chip active={risk === "MEDIUM"} onClick={() => reset(() => setRisk(risk === "MEDIUM" ? "" : "MEDIUM"))}>
              Medium risk · {summary.medium_risk}
            </Chip>
            <Chip active={refillOnly} onClick={() => reset(() => setRefillOnly(!refillOnly))}>
              Refill from backroom · {summary.refill_needed}
            </Chip>
            <span className="text-sm text-ink-secondary">
              {summary.shortage_products} of {summary.products} products below requirement ·{" "}
              {formatNumber(summary.near_expiry_qty)} units expire within 7 days
            </span>
          </>
        ) : null}
      </div>
      <DataTable
        caption="Store inventory"
        columns={PRODUCT_COLUMNS}
        page={result.data}
        query={query}
        onQueryChange={setQuery}
        getRowId={(r) => r.product.product_id}
        isLoading={result.isPending}
        isFetching={result.isFetching}
        error={result.error ? result.error.message : null}
        onRetry={() => void result.refetch()}
        onRowClick={onOpen}
        search={{ value: search, onChange: (v) => reset(() => setSearch(v)), placeholder: "Search product or SKU" }}
        filters={
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            Category
            <select
              className="h-10 rounded-input border border-border bg-surface px-2 text-ink"
              value={category}
              onChange={(e) => reset(() => setCategory(e.target.value))}
            >
              <option value="">All categories</option>
              {KNOWN_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {categoryLabel(c)}
                </option>
              ))}
            </select>
          </label>
        }
        emptyTitle="No products match"
        emptyDescription="Change the search, category or summary filter."
      />
    </div>
  );
}

// --- stock moves tab ------------------------------------------------------------------------------------------

const MOVEMENT_COLUMNS: Column<InventoryMovementDTO>[] = [
  // Fixed order, newest first (cursor paging, D-37): no column is sortable.
  { id: "occurred_at", header: "When", hideable: false, cell: (m) => formatDateTimeIST(m.occurred_at) },
  { id: "name", header: "Product", cell: (m) => m.product.name },
  { id: "movement_type", header: "Movement", cell: (m) => MOVEMENT_LABEL[m.movement_type] },
  {
    id: "qty",
    header: "Quantity",
    align: "right",
    cell: (m) => <span className={m.qty < 0 ? "text-danger" : "text-success"}>{signed(m.qty)}</span>,
  },
  { id: "location", header: "Location", cell: (m) => (m.location === "SHELF" ? "Shelf" : "Backroom") },
  { id: "reference", header: "Reference", cell: (m) => m.reference ?? "—" },
  { id: "reason", header: "Reason", cell: (m) => m.reason ?? "—" },
];

function MovesTab({ storeId }: { storeId: string }) {
  const paging = useCursorPaging();
  const [type, setType] = useState<MovementType | "">("");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const result = useStoreMovements(storeId, {
    cursor: paging.cursor,
    page_size: paging.query.pageSize,
    q: q || undefined,
    type: type || undefined,
  });
  return (
    <DataTable
      caption="Stock moves (movement ledger)"
      columns={MOVEMENT_COLUMNS}
      page={result.data}
      paging="cursor"
      query={paging.query}
      onQueryChange={(next) => paging.onQueryChange(next, result.data?.next_cursor)}
      getRowId={(m) => m.movement_id}
      isLoading={result.isPending}
      isFetching={result.isFetching}
      error={result.error ? result.error.message : null}
      onRetry={() => void result.refetch()}
      search={{
        value: search,
        onChange: (v) => {
          setSearch(v);
          paging.reset();
        },
        placeholder: "Search product or SKU",
      }}
      filters={
        <label className="flex items-center gap-2 text-sm text-ink-secondary">
          Movement
          <select
            className="h-10 rounded-input border border-border bg-surface px-2 text-ink"
            value={type}
            onChange={(e) => {
              setType(e.target.value as MovementType | "");
              paging.reset();
            }}
          >
            <option value="">All movements</option>
            {(Object.keys(MOVEMENT_LABEL) as MovementType[]).map((t) => (
              <option key={t} value={t}>
                {MOVEMENT_LABEL[t]}
              </option>
            ))}
          </select>
        </label>
      }
      emptyTitle="No stock moves"
    />
  );
}

// --- batches / expiring tabs ---------------------------------------------------------------------------------

const BATCH_COLUMNS: Column<BatchDTO>[] = [
  {
    id: "name",
    header: "Product",
    sortable: true,
    hideable: false,
    cell: (b) => (
      <span>
        <span className="font-medium text-ink">{b.product.name}</span>
        <span className="block text-xs text-ink-secondary">{b.product.sku}</span>
      </span>
    ),
  },
  { id: "batch_no", header: "Batch", cell: (b) => b.batch_no },
  { id: "qty", header: "Quantity", sortable: true, align: "right", cell: (b) => formatNumber(b.qty) },
  { id: "expiry_date", header: "Expiry date", sortable: true, cell: (b) => formatDateIST(b.expiry_date) },
  { id: "days_left", header: "Days left", sortable: true, align: "right", cell: (b) => formatNumber(b.days_left) },
  {
    id: "fefo_rank",
    header: "Sells",
    align: "right",
    cell: (b) => (b.fefo_rank === 1 ? "First (FEFO)" : `#${b.fefo_rank}`),
  },
  {
    id: "at_risk_qty",
    header: "Expiry risk",
    sortable: true,
    cell: (b) =>
      b.at_risk_qty > 0 ? (
        <StatusBadge tone="danger" label={`${formatNumber(b.at_risk_qty)} will not sell in time`} />
      ) : (
        <StatusBadge tone="success" label="Sells in time" />
      ),
  },
];

function BatchesTab({ storeId, expiring }: { storeId: string; expiring: boolean }) {
  const [query, setQuery] = useState<TableQuery>({
    page: 1,
    pageSize: 25,
    sort: expiring ? "days_left" : "expiry_date",
  });
  const params = { page: query.page, page_size: query.pageSize, sort: query.sort };
  const batches = useStoreBatches(expiring ? null : storeId, params);
  const soon = useStoreExpiring(expiring ? storeId : null, { ...params, within_days: 14 });
  const result = expiring ? soon : batches;
  return (
    <DataTable
      caption={expiring ? "Batches expiring within 14 days" : "Batches (earliest expiry first)"}
      columns={BATCH_COLUMNS}
      page={result.data}
      query={query}
      onQueryChange={setQuery}
      getRowId={(b) => b.batch_id}
      isLoading={result.isPending}
      isFetching={result.isFetching}
      error={result.error ? result.error.message : null}
      onRetry={() => void result.refetch()}
      emptyTitle={expiring ? "Nothing expires in the next 14 days" : "No batches tracked"}
      emptyDescription="Batches are tracked for perishable products."
    />
  );
}

// --- product drawer --------------------------------------------------------------------------------------------

function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {children}
    </section>
  );
}

function ProductDrawer({ storeId, row, onClose }: { storeId: string; row: InventoryRowDTO; onClose: () => void }) {
  const productId = row.product.product_id;
  const recs = useRecommendations({ store_id: storeId, product_id: productId, page_size: 10 });
  const transfers = useTransfers({ store_id: storeId, product_id: productId, page_size: 10 });
  const batches = useStoreBatches(storeId, { product_id: productId, page_size: 20 });
  const stock: Array<[string, ReactNode]> = [
    ["Shelf", `${formatNumber(row.shelf_qty)} (minimum ${formatNumber(row.shelf_min)})`],
    ["Backroom", formatNumber(row.backroom_qty)],
    ["Incoming", formatNumber(row.incoming)],
    ["Reserved", formatNumber(row.reserved)],
    ["Available", formatNumber(row.available)],
    ["Own requirement", formatNumber(row.own_requirement)],
    ["Surplus / shortage", signed(row.surplus_or_shortage)],
    ["Days of cover", formatDays(row.days_of_cover)],
    ["Stockout risk", <StatusPill key="risk" status={row.stockout_risk} />],
  ];
  return (
    <Modal
      open
      variant="drawer"
      title={row.product.name}
      description={`${row.product.sku} · ${categoryLabel(row.product.category)}`}
      onClose={onClose}
    >
      <div className="space-y-6">
        <DrawerSection title="Stock">
          {row.refill_from_backroom ? (
            <StatusBadge tone="warning" icon={PackageOpen} label="Shelf below minimum — refill from backroom" />
          ) : null}
          <dl className="text-sm">
            {stock.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 border-b border-divider py-1.5 last:border-b-0">
                <dt className="text-ink-secondary">{label}</dt>
                <dd className="tabular font-medium">{value}</dd>
              </div>
            ))}
          </dl>
        </DrawerSection>
        <DrawerSection title="Recommendations">
          {recs.isPending ? (
            <p className="text-sm text-ink-secondary">Loading…</p>
          ) : recs.data?.items.length ? (
            <ul className="space-y-2">
              {recs.data.items.map((r) => (
                <li key={r.rec_id} className="flex items-center justify-between gap-2 text-sm">
                  <Link className="text-brand underline" to={`/recommendations/${r.rec_id}`}>
                    {REC_TYPE_LABEL[r.rec_type]} · {formatNumber(r.qty)} units
                  </Link>
                  <StatusPill status={r.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-secondary">No recommendations for this product.</p>
          )}
        </DrawerSection>
        <DrawerSection title="Open transfers">
          {transfers.data?.items.length ? (
            <ul className="space-y-2">
              {transfers.data.items.map((t) => (
                <li key={t.transfer_id} className="flex items-center justify-between gap-2 text-sm">
                  <span>
                    {t.from_store.store_id === storeId ? `To ${t.to_store.name}` : `From ${t.from_store.name}`} ·{" "}
                    {formatNumber(t.qty)} units{t.is_expiry_aware ? " (expiring batch)" : ""}
                  </span>
                  <StatusPill status={t.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-secondary">{transfers.isPending ? "Loading…" : "No open transfers."}</p>
          )}
        </DrawerSection>
        <DrawerSection title="Batches (earliest expiry first)">
          {batches.data?.items.length ? (
            <ul className="space-y-2">
              {batches.data.items.map((b) => (
                <li key={b.batch_id} className="flex items-center justify-between gap-2 text-sm">
                  <span>
                    {b.batch_no} · {formatNumber(b.qty)} units · expires {formatDateIST(b.expiry_date)}
                  </span>
                  {b.at_risk_qty > 0 ? (
                    <StatusBadge tone="danger" label={`${formatNumber(b.at_risk_qty)} at risk`} />
                  ) : (
                    <StatusBadge tone="success" label="Sells in time" />
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-secondary">
              {batches.isPending ? "Loading…" : "No batches tracked for this product."}
            </p>
          )}
        </DrawerSection>
      </div>
    </Modal>
  );
}

// --- page --------------------------------------------------------------------------------------------------------

function StorePicker({ stores, onPick }: { stores: StoreDTO[]; onPick: (id: string) => void }) {
  return (
    <section aria-labelledby="pick-store" className="rounded-card border border-border bg-surface p-6 shadow-card">
      <h2 id="pick-store" className="text-lg font-semibold text-ink">
        Choose a store
      </h2>
      <p className="mt-1 text-sm text-ink-secondary">Inventory is shown for one store at a time.</p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-3">
        {stores.map((s) => (
          <li key={s.store_id}>
            <button
              type="button"
              onClick={() => onPick(s.store_id)}
              className="flex w-full items-center gap-3 rounded-card border border-border p-4 text-left hover:border-brand hover:bg-brand-soft"
            >
              <Store aria-hidden="true" className="text-brand" size={20} />
              <span>
                <span className="block font-medium text-ink">{s.name}</span>
                <span className="block text-xs text-ink-secondary">{s.region}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function InventoryPage() {
  const { user } = useAuth();
  const shell = useShell();
  const isAdmin = user?.role === "SUPER_ADMIN";
  const stores = useStores(isAdmin);
  const [picked, setPicked] = useState<string | null>(() => (isAdmin ? readLastStore() : null));
  const [tab, setTab] = useState("products");
  const [open, setOpen] = useState<InventoryRowDTO | null>(null);

  const storeId = isAdmin ? (shell.storeId ?? picked) : (user?.store?.store_id ?? null);

  useEffect(() => {
    if (isAdmin && shell.storeId) writeLastStore(shell.storeId);
  }, [isAdmin, shell.storeId]);

  const choose = (id: string) => {
    setPicked(id);
    writeLastStore(id);
    if (shell.storeId) shell.setStoreId(id);
  };

  if (!storeId) {
    return stores.data ? (
      <StorePicker stores={stores.data} onPick={choose} />
    ) : (
      <p className="text-sm text-ink-secondary">Loading stores…</p>
    );
  }

  return (
    <div className="space-y-4">
      {isAdmin ? (
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            Inventory for
            <select
              className="h-10 rounded-input border border-border bg-surface px-2 text-ink"
              value={storeId}
              onChange={(e) => choose(e.target.value)}
            >
              {stores.data?.map((s) => (
                <option key={s.store_id} value={s.store_id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          {shell.storeId === null ? (
            <Button variant="tertiary" size="sm" onClick={() => setPicked(null)}>
              Choose another store
            </Button>
          ) : null}
        </div>
      ) : null}
      <Tabs
        label="Inventory views"
        value={tab}
        onChange={setTab}
        items={[
          { key: "products", label: "All products" },
          { key: "moves", label: "Stock moves" },
          { key: "batches", label: "Batches" },
          { key: "expiring", label: "Expiring soon" },
        ]}
      >
        {tab === "products" ? <ProductsTab key={storeId} storeId={storeId} onOpen={setOpen} /> : null}
        {tab === "moves" ? <MovesTab key={storeId} storeId={storeId} /> : null}
        {tab === "batches" ? <BatchesTab key={`b-${storeId}`} storeId={storeId} expiring={false} /> : null}
        {tab === "expiring" ? <BatchesTab key={`e-${storeId}`} storeId={storeId} expiring /> : null}
      </Tabs>
      {open ? <ProductDrawer storeId={storeId} row={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}
