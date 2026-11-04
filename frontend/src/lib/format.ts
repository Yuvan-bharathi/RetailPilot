/**
 * Shared formatters: en-IN grouping, ₹ compact (₹42.8L, ₹1.2Cr), IST dates (CLAUDE.md: UTC stored, IST shown).
 * Money arrives from the API as 2-decimal strings (Money in the OpenAPI contract) and is never parsed into
 * arithmetic here — only into display.
 */

const IST = "Asia/Kolkata";

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const inrWhole = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const integer = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const decimal1 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function toNumber(value: string | number): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) throw new Error(`not a number: ${value}`);
  return n;
}

/** ₹1,23,456.50 (Indian digit grouping). */
export function formatINR(value: string | number, options: { whole?: boolean } = {}): string {
  const n = toNumber(value);
  return (options.whole ? inrWhole : inr).format(n);
}

/** ₹42.8L, ₹1.2Cr, ₹12.5K, ₹950 — for KPI cards. */
export function formatINRCompact(value: string | number): string {
  const n = toNumber(value);
  const sign = n < 0 ? "−" : "";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `${sign}₹${decimal1.format(abs / 1e7)}Cr`;
  if (abs >= 1e5) return `${sign}₹${decimal1.format(abs / 1e5)}L`;
  if (abs >= 1e3) return `${sign}₹${decimal1.format(abs / 1e3)}K`;
  return `${sign}₹${integer.format(abs)}`;
}

/** 1,23,456 */
export function formatNumber(value: number): string {
  return integer.format(value);
}

/** 12.5% from a ratio (0.125) */
export function formatPercent(ratio: number, digits = 1): string {
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** 3.2 days */
export function formatDays(days: number): string {
  return `${decimal1.format(days)} days`;
}

/** 3 Nov 2026 — accepts an ISO date (YYYY-MM-DD) or datetime. A plain date is a calendar day, not shifted. */
export function formatDateIST(value: string): string {
  const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = new Date(isDateOnly ? `${value}T00:00:00Z` : value);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: isDateOnly ? "UTC" : IST,
  }).format(date);
}

/** 3 Nov 2026, 23:45 IST */
export function formatDateTimeIST(value: string): string {
  const text = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: IST,
  }).format(new Date(value));
  return `${text} IST`;
}
