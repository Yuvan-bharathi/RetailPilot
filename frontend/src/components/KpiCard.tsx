import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";

import type { Tone } from "./StatusBadge";

export interface Trend {
  direction: "up" | "down" | "flat";
  label: string; // e.g. "+4.2% vs last 28 days"
  tone: Extract<Tone, "success" | "danger" | "neutral">; // good / bad / neutral — not inferred from direction
}

const TREND_CLASSES: Record<Trend["tone"], string> = {
  success: "bg-success-bg text-success",
  danger: "bg-danger-bg text-danger",
  neutral: "bg-neutral-bg text-neutral",
};

export function KpiCard({ title, value, trend, meta }: { title: string; value: string; trend?: Trend; meta?: string }) {
  const Arrow = trend?.direction === "up" ? ArrowUpRight : trend?.direction === "down" ? ArrowDownRight : ArrowRight;
  return (
    <section className="rounded-card border border-border bg-surface p-4 shadow-card" aria-label={title}>
      <h3 className="text-sm font-semibold text-ink-secondary">{title}</h3>
      <p className="tabular mt-2 text-[26px] leading-8 font-semibold text-ink">{value}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {trend ? (
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${TREND_CLASSES[trend.tone]}`}>
            <Arrow aria-hidden="true" size={12} />
            {trend.label}
          </span>
        ) : null}
        {meta ? <span className="text-ink-secondary">{meta}</span> : null}
      </div>
    </section>
  );
}
