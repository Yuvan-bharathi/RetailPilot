/** Human-readable labels for contract enums (sentence case, design doc §2). */
import type {
  MovementType,
  NeedsReviewEvidence,
  ReorderEvidence,
  RecType,
  StockoutRisk,
} from "../api/types";

export const REC_TYPE_LABEL: Record<RecType, string> = {
  REORDER: "Reorder",
  TRANSFER: "Transfer",
  CO_REPLENISH: "Co-replenish",
  MARKDOWN: "Markdown",
  EXPIRY_ALERT: "Expiry alert",
  ASSORTMENT_GAP: "Assortment gap",
};

export const MOVEMENT_LABEL: Record<MovementType, string> = {
  SALE: "Sale",
  PO_RECEIPT: "Goods receipt",
  TRANSFER_OUT: "Transfer out",
  TRANSFER_IN: "Transfer in",
  SHELF_REFILL: "Shelf refill",
  ADJUSTMENT: "Adjustment",
  EXPIRY_WRITE_OFF: "Expiry write-off",
};

export const NEED_REASON_TEXT: Record<ReorderEvidence["reason"], string> = {
  NO_SURPLUS_IN_ANY_STORE: "No other store has stock to spare",
  PARTIAL_SURPLUS: "Other stores could cover only part of the need",
  TRANSFER_NOT_VIABLE: "A transfer would cost more or arrive later than a supplier delivery",
};

export const REVIEW_REASON_TEXT: Record<NeedsReviewEvidence["reason"], string> = {
  LOW_CONFIDENCE: "Forecast is unreliable (stale or too little data)",
  BUDGET: "Did not fit this week's budget",
  NO_ELIGIBLE_SUPPLIER: "No supplier can deliver in time",
};

export const RISK_LABEL: Record<StockoutRisk, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };

/** "personal_care" → "Personal care" */
export function categoryLabel(category: string): string {
  const text = category.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Product categories of the PoC catalogue (synthetic data); the real list will come from master data. */
export const KNOWN_CATEGORIES = [
  "staples",
  "dairy",
  "bakery",
  "biscuits",
  "beverages",
  "personal_care",
  "household",
] as const;
