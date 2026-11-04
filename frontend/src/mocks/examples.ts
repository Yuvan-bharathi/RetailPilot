/**
 * Small typed evidence examples for the /components demo page and component tests — one per evidence kind,
 * including the kinds the synthetic data does not produce today (NEEDS_REVIEW, ASSORTMENT_GAP).
 */
import type { Evidence } from "../api/types";

const STORE_A = { store_id: "00000000-0000-4000-8000-00000000000a", name: "Store A - Residential" };
const STORE_C = { store_id: "00000000-0000-4000-8000-00000000000c", name: "Store C - Temple street" };
const product = (n: number, name: string, category: string) => ({
  product_id: `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`,
  sku: `DEMO-${n}`,
  name,
  category,
});

export const EXAMPLE_EVIDENCE: Record<Evidence["kind"] | "TRANSFER_DESTINATION", Evidence> = {
  TRANSFER: {
    kind: "TRANSFER",
    destination_shortage: 40,
    donor: { store: STORE_A, qty: 24 },
    donor_surplus: 24,
    donor_protected_requirement: 30,
    donor_keeps_requirement: true,
    transfer_qty: 24,
    po_remainder_qty: 16,
    transfer_cost: "222.00",
    po_incremental_cost: "451.80",
    expected_delivery: "2026-11-04",
    days_of_cover_before: 0,
    days_of_cover_after: 6,
  },
  TRANSFER_DESTINATION: {
    kind: "TRANSFER",
    destination_shortage: 40,
    donor: { store: STORE_A, qty: 24 },
    donor_surplus: null,
    donor_protected_requirement: null,
    donor_keeps_requirement: true,
    transfer_qty: 24,
    po_remainder_qty: 16,
    transfer_cost: "222.00",
    po_incremental_cost: "451.80",
    expected_delivery: "2026-11-04",
    days_of_cover_before: 0,
    days_of_cover_after: 6,
  },
  REORDER: {
    kind: "REORDER",
    reason: "PARTIAL_SURPLUS",
    daily_demand: 4,
    lead_time_days: 5,
    review_period_days: 3,
    safety_stock_days: 1,
    min_display_qty: 4,
    own_requirement: 40,
    available: 0,
    need_qty: 40,
    transferred_qty: 24,
    days_of_cover: 0,
    supplier: { supplier_id: "00000000-0000-4000-8000-0000000000f3", name: "Scenario supplier 3 (synthetic)" },
    lost_revenue: "560.00",
    lost_profit: "120.00",
  },
  CO_REPLENISH: {
    kind: "CO_REPLENISH",
    linked_product: product(1, "Bread 400 g (demo)", "bakery"),
    support: 0.0135,
    confidence: 0.27,
    lift: 18.2,
    daily_demand: 3,
    review_period_days: 2,
    own_requirement: 22,
    available: 25,
    projected_at_next_review: 19,
    supplier: { supplier_id: "00000000-0000-4000-8000-0000000000f4", name: "Scenario supplier 4 (synthetic)" },
  },
  EXPIRY: {
    kind: "EXPIRY",
    batch: { batch_no: "A-DEMO-007", expiry_date: "2026-11-08", days_left: 5, batch_qty: 40, at_risk_qty: 30 },
    daily_demand: 2,
    receivers_checked: 2,
    markdown_pct: null,
  },
  ASSORTMENT_GAP: {
    kind: "ASSORTMENT_GAP",
    antecedent: product(2, "Tea 250 g (demo)", "beverages"),
    lift: 2.4,
    source_stores: [STORE_A, STORE_C],
  },
  NEEDS_REVIEW: {
    kind: "NEEDS_REVIEW",
    reason: "LOW_CONFIDENCE",
    own_requirement: 18,
    available: 6,
    suggested_qty: 12,
    detail: "No sales for more than 3 days while stock is held.",
  },
};
