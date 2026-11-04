/**
 * Mock data for the UI until the Phase 6 API exists (VITE_USE_MOCKS=true). Every value is typed by the generated
 * OpenAPI DTOs, so a contract change breaks this file at compile time. Numbers follow the demo scenarios.
 */
import type {
  DashboardSummary,
  InventoryRowDTO,
  ProductRef,
  PurchaseOrderDTO,
  RecommendationDTO,
  RecStatus,
  RecType,
  Role,
  RunInfoDTO,
  StoreDTO,
  StoreRef,
  TransferEvidenceDTO,
  TransferOrderDTO,
} from "../api/types";

const id = (n: number, prefix = "0000"): string => `${prefix}0000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;

export const STORES: StoreDTO[] = [
  { store_id: id(0xa, "a001"), code: "A", name: "Store A - Residential", region: "Chennai", store_type: "residential" },
  { store_id: id(0xb, "a001"), code: "B", name: "Store B - College area", region: "Chennai", store_type: "college" },
  { store_id: id(0xc, "a001"), code: "C", name: "Store C - Temple street", region: "Chennai", store_type: "temple" },
];
const [STORE_A, STORE_B, STORE_C] = STORES as [StoreDTO, StoreDTO, StoreDTO];
export const storeRef = (s: StoreDTO): StoreRef => ({ store_id: s.store_id, name: s.name });

export interface MockUser {
  username: string;
  user_id: string;
  name: string;
  role: Role;
  store: StoreDTO | null;
}

export const MOCK_PASSWORD = "demo";
export const USERS: MockUser[] = [
  { username: "admin", user_id: id(1, "u001"), name: "Super Admin", role: "SUPER_ADMIN", store: null },
  { username: "sup.a", user_id: id(2, "u001"), name: "Asha (Store A)", role: "STORE_SUPERVISOR", store: STORE_A },
  { username: "sup.b", user_id: id(3, "u001"), name: "Bala (Store B)", role: "STORE_SUPERVISOR", store: STORE_B },
  { username: "sup.c", user_id: id(4, "u001"), name: "Chitra (Store C)", role: "STORE_SUPERVISOR", store: STORE_C },
];

const PRODUCT_NAMES: Array<[string, string]> = [
  ["Biscuits 200 g", "biscuits"],
  ["Rice 5 kg", "staples"],
  ["Tea 250 g", "beverages"],
  ["Bread 400 g", "bakery"],
  ["Butter 100 g", "dairy"],
  ["Paneer 200 g", "dairy"],
  ["Toor dal 1 kg", "staples"],
  ["Sunflower oil 1 L", "staples"],
  ["Detergent 1 kg", "household"],
  ["Toothpaste 150 g", "personal_care"],
  ["Coffee 200 g", "beverages"],
  ["Curd 400 g", "dairy"],
  ["Atta 5 kg", "staples"],
  ["Soap 4-pack", "personal_care"],
  ["Namkeen 150 g", "biscuits"],
  ["Dishwash bar", "household"],
];
export const PRODUCTS: ProductRef[] = PRODUCT_NAMES.map(([name, category], i) => ({
  product_id: id(i + 1, "b001"),
  sku: `SKU${String(i + 1).padStart(4, "0")}`,
  name,
  category,
}));
const P = (i: number): ProductRef => PRODUCTS[i % PRODUCTS.length] as ProductRef;

export const LATEST_RUN: RunInfoDTO = {
  run_id: id(0x99, "c001"),
  run_date: "2026-11-03",
  status: "SUCCESS",
  finished_at: "2026-11-02T18:42:00Z", // 00:12 IST on 3 Nov
};

// --- recommendations --------------------------------------------------------------------------------------------

const REC_TYPES: RecType[] = ["REORDER", "TRANSFER", "CO_REPLENISH", "EXPIRY_ALERT", "ASSORTMENT_GAP", "REORDER"];
const REC_STATUSES: RecStatus[] = ["PENDING", "PENDING", "ACCEPTED", "NEEDS_REVIEW", "PENDING", "REJECTED"];

/** Scenario 3: Store C short 40; Store A offers 24 → transfer 24 + PO 16 for C. */
export const CROSS_STORE_TRANSFER_REC: RecommendationDTO = {
  rec_id: id(0x301, "d001"),
  run_id: LATEST_RUN.run_id,
  store: storeRef(STORE_C),
  product: P(0),
  rec_type: "TRANSFER",
  status: "PENDING",
  priority: "HIGH",
  qty: 24,
  lost_revenue: "560.00",
  explanation:
    "Transfer 24 units from Store A, which holds more than it needs before its next delivery; order the remaining 16 from the supplier.",
  counterpart: { store: storeRef(STORE_A), qty: 24 },
  created_at: "2026-11-02T18:40:00Z",
};

/** Evidence as the Super Admin sees it; supervisors get donor_surplus / donor_protected_requirement = null. */
export const CROSS_STORE_EVIDENCE_ADMIN: TransferEvidenceDTO = {
  destination_shortage: 40,
  donor: { store: storeRef(STORE_A), qty: 24 },
  donor_surplus: 24,
  donor_protected_requirement: 30,
  transfer_qty: 24,
  po_remainder_qty: 16,
  transfer_cost: "222.00",
  po_incremental_cost: "451.80",
  expected_delivery: "2026-11-04",
  days_of_cover_before: 0,
  days_of_cover_after: 6,
};

export const RECOMMENDATIONS: RecommendationDTO[] = [
  CROSS_STORE_TRANSFER_REC,
  ...Array.from({ length: 41 }, (_, i): RecommendationDTO => {
    const store = STORES[i % 3] as StoreDTO;
    const recType = REC_TYPES[i % REC_TYPES.length] as RecType;
    const donor = STORES[(i + 1) % 3] as StoreDTO;
    return {
      rec_id: id(0x400 + i, "d001"),
      run_id: LATEST_RUN.run_id,
      store: storeRef(store),
      product: P(i + 1),
      rec_type: recType,
      status: REC_STATUSES[i % REC_STATUSES.length] as RecStatus,
      priority: i % 4 === 0 ? "HIGH" : "NORMAL",
      qty: 6 + ((i * 7) % 60),
      lost_revenue: i % 3 === 0 ? `${(1250 + i * 375).toFixed(2)}` : null,
      explanation: null,
      counterpart: recType === "TRANSFER" ? { store: storeRef(donor), qty: 10 + (i % 20) } : null,
      created_at: "2026-11-02T18:40:00Z",
    };
  }),
];

// --- inventory -------------------------------------------------------------------------------------------------------

export function inventoryRows(storeIndex: number): InventoryRowDTO[] {
  return PRODUCTS.map((product, i) => {
    const seed = (i + 1) * (storeIndex + 3);
    const shelf = seed % 17;
    const backroom = (seed * 3) % 40;
    const incoming = i % 5 === 0 ? 12 : 0;
    const reserved = i % 7 === 0 ? 4 : 0;
    const available = shelf + backroom + incoming - reserved;
    const requirement = 20 + (seed % 25);
    const demand = 2 + (seed % 6);
    const cover = available / demand;
    const shelfMin = 6 + (i % 5);
    return {
      product,
      shelf_qty: shelf,
      shelf_min: shelfMin,
      backroom_qty: backroom,
      incoming,
      reserved,
      available,
      own_requirement: requirement,
      surplus_or_shortage: available - requirement,
      days_of_cover: Math.round(cover * 10) / 10,
      stockout_risk: cover < 3 ? "HIGH" : cover < 6 ? "MEDIUM" : "LOW",
      near_expiry_qty: product.category === "dairy" ? seed % 9 : 0,
      pending_transfer_in: i === 0 && storeIndex === 2 ? 24 : 0,
      pending_transfer_out: i === 0 && storeIndex === 0 ? 24 : 0,
      refill_from_backroom: shelf < shelfMin && backroom > 0,
    };
  });
}

// --- transfers and purchase orders -------------------------------------------------------------------------------

export const TRANSFERS: TransferOrderDTO[] = [
  {
    transfer_id: id(0x501, "e001"),
    product: P(0),
    from_store: storeRef(STORE_A),
    to_store: storeRef(STORE_C),
    qty: 24,
    status: "PROPOSED",
    is_expiry_aware: false,
    transit_days: 1,
    transfer_cost: "222.00",
    created_at: "2026-11-02T18:40:00Z",
    received_qty: null,
  },
  {
    transfer_id: id(0x502, "e001"),
    product: P(2),
    from_store: storeRef(STORE_A),
    to_store: storeRef(STORE_C),
    qty: 20,
    status: "DEST_ACCEPTED",
    is_expiry_aware: false,
    transit_days: 1,
    transfer_cost: "210.00",
    created_at: "2026-11-01T18:40:00Z",
    received_qty: null,
  },
  {
    transfer_id: id(0x503, "e001"),
    product: P(5),
    from_store: storeRef(STORE_A),
    to_store: storeRef(STORE_C),
    qty: 30,
    status: "DISPATCHED",
    is_expiry_aware: true,
    transit_days: 1,
    transfer_cost: "240.00",
    created_at: "2026-10-31T18:40:00Z",
    received_qty: null,
  },
  {
    transfer_id: id(0x504, "e001"),
    product: P(7),
    from_store: storeRef(STORE_B),
    to_store: storeRef(STORE_A),
    qty: 12,
    status: "RECEIVED",
    is_expiry_aware: false,
    transit_days: 2,
    transfer_cost: "196.00",
    created_at: "2026-10-28T18:40:00Z",
    received_qty: 11,
  },
];

export const PURCHASE_ORDERS: PurchaseOrderDTO[] = [
  {
    po_id: id(0x601, "f001"),
    supplier: { supplier_id: id(0x71, "f101"), name: "Staples distributor 1" },
    status: "PENDING_L1",
    required_level: "L1",
    total_value: "47120.00",
    l1_deadline: "2026-11-03T18:30:00Z",
    parent_po_id: null,
    flags: [],
    lines: STORES.map((store, i) => ({
      po_line_id: id(0x611 + i, "f001"),
      store: storeRef(store),
      product: P(1),
      qty: [35, 45, 51][i] as number,
      unit_price: "380.00",
      line_value: `${(([35, 45, 51][i] as number) * 380).toFixed(2)}`,
      line_status: (["APPROVED", "PENDING", "PENDING"] as const)[i] ?? "PENDING",
      received_qty: 0,
    })),
    other_store_lines: [],
    created_at: "2026-11-02T18:41:00Z",
  },
];

// --- dashboard ----------------------------------------------------------------------------------------------------

export function dashboard(store: StoreDTO | null, period: DashboardSummary["period"]): DashboardSummary {
  const scale = store ? 1 : 3;
  return {
    store: store ? storeRef(store) : null,
    period,
    revenue: `${(1_426_000 * scale).toFixed(2)}`,
    gross_profit: `${(256_700 * scale).toFixed(2)}`,
    margin_pct: 0.18,
    stockout_rate: 0.034,
    lost_revenue: `${(48_250 * scale).toFixed(2)}`,
    lost_profit: `${(8_690 * scale).toFixed(2)}`,
    inventory_value: `${(2_180_000 * scale).toFixed(2)}`,
    near_expiry_value: `${(12_400 * scale).toFixed(2)}`,
    pending_recommendations: 14 * scale,
    pending_purchase_orders: 2 * scale,
    active_transfers: 3,
    fast_movers: PRODUCTS.slice(0, 3).map((product, i) => ({ product, units: 820 - i * 140, revenue: `${(92_000 - i * 9_000).toFixed(2)}` })),
    slow_movers: PRODUCTS.slice(8, 11).map((product, i) => ({ product, units: 6 + i, revenue: `${(900 + i * 75).toFixed(2)}` })),
  };
}
