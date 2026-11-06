/** Shared display helpers of the agent console (docs/09 §6): statuses use semantic tokens + icon + text label. */
import { Bot, Cpu, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";

import type { DecisionOutcome } from "../../api/types";
import { RUN_STATUS, type AnyStatus } from "../../lib/agentFormat";
import { formatDateTimeIST } from "../../lib/format";
import { StatusBadge, type Tone } from "../StatusBadge";

export function RunStatusBadge({ status }: { status: AnyStatus }) {
  const s = RUN_STATUS[status] ?? RUN_STATUS.NOT_RUN;
  return <StatusBadge tone={s.tone} label={s.label} icon={s.icon} />;
}

const OUTCOME: Record<DecisionOutcome, { tone: Tone; label: string }> = {
  PENDING: { tone: "info", label: "Pending" },
  ACCEPTED: { tone: "success", label: "Accepted" },
  EDITED: { tone: "success", label: "Edited" },
  REJECTED: { tone: "danger", label: "Rejected" },
  SUPERSEDED: { tone: "neutral", label: "Superseded" },
  NOT_APPLICABLE: { tone: "neutral", label: "No action needed" },
};

export function OutcomeBadge({ outcome }: { outcome: DecisionOutcome }) {
  const s = OUTCOME[outcome];
  return <StatusBadge tone={s.tone} label={s.label} />;
}

export function KindBadge({ kind }: { kind: "DETERMINISTIC" | "LLM" }) {
  return kind === "LLM" ? (
    <StatusBadge tone="info" label="LLM agent" icon={Sparkles} />
  ) : (
    <StatusBadge tone="neutral" label="Deterministic" icon={Cpu} />
  );
}

export function AgentLink({ agentKey, name }: { agentKey: string | null; name: string }) {
  if (!agentKey) return <span className="font-medium text-ink">{name}</span>;
  return (
    <Link
      to={`/agents/${agentKey}`}
      className="inline-flex items-center gap-1.5 font-medium text-brand hover:underline"
    >
      <Bot aria-hidden="true" size={14} />
      {name}
    </Link>
  );
}

export function When({ at }: { at: string | null | undefined }) {
  return <span className="tabular whitespace-nowrap">{at ? formatDateTimeIST(at) : "—"}</span>;
}

/** Section card used across the console pages. */
export function Panel({
  title,
  actions,
  children,
  className = "",
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-card border border-border bg-surface shadow-card ${className}`}>
      {title || actions ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-divider px-4 py-3">
          {title ? <h2 className="text-sm font-semibold text-ink">{title}</h2> : <span />}
          {actions}
        </div>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Sub-navigation shared by the console pages (the sidebar lists them too). */
export function ConsoleTabs() {
  const items = [
    { to: "/agents", label: "Overview" },
    { to: "/agents/pipeline", label: "Pipeline" },
    { to: "/agents/flow", label: "Visual flow" },
    { to: "/agents/logs", label: "Logs" },
    { to: "/agents/decisions", label: "Decisions" },
  ];
  const path = useLocation().pathname;
  return (
    <nav aria-label="Agent console" className="flex flex-wrap gap-1 border-b border-border">
      {items.map((i) => {
        const active = path === i.to;
        return (
          <Link
            key={i.to}
            to={i.to}
            aria-current={active ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              active ? "border-brand font-semibold text-brand" : "border-transparent text-ink-secondary hover:text-ink"
            }`}
          >
            {i.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Select<T extends string>({
  label,
  value,
  onChange,
  options,
  allLabel = "All",
}: {
  label: string;
  value: T | "";
  onChange: (v: T | "") => void;
  options: Array<{ value: T; label: string }>;
  allLabel?: string;
}) {
  return (
    <label className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
      {label}
      <select
        className="h-8 rounded-input border border-border bg-surface px-2 text-xs text-ink"
        value={value}
        onChange={(e) => onChange(e.target.value as T | "")}
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
