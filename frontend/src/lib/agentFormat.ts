/** Labels and formatting of the agent console (docs/09 §6). Status colours: semantic tokens via `Tone`. */
import {
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  Hourglass,
  Loader2,
  OctagonAlert,
  PauseCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import type { AgentPattern, DecisionOutcome, RunStatus, TriggerType } from "../api/types";
import type { Tone } from "../components/StatusBadge";

export type AnyStatus = RunStatus | "NOT_RUN" | "WAITING" | "DONE";

export const RUN_STATUS: Record<AnyStatus, { tone: Tone; label: string; icon: LucideIcon }> = {
  RUNNING: { tone: "info", label: "Running", icon: Loader2 },
  SUCCESS: { tone: "success", label: "Success", icon: CheckCircle2 },
  PARTIAL: { tone: "warning", label: "Partial", icon: TriangleAlert },
  FAILED: { tone: "danger", label: "Failed", icon: OctagonAlert },
  SKIPPED_DISABLED: { tone: "neutral", label: "Skipped — disabled", icon: CircleSlash },
  SKIPPED_DEPENDENCY: { tone: "neutral", label: "Skipped — dependency", icon: CircleDashed },
  PAUSED: { tone: "attention", label: "Paused", icon: PauseCircle },
  CANCELLED: { tone: "neutral", label: "Cancelled", icon: Ban },
  NOT_RUN: { tone: "neutral", label: "Not run", icon: CircleDashed },
  WAITING: { tone: "attention", label: "Waiting for people", icon: Hourglass },
  DONE: { tone: "success", label: "Done", icon: CheckCircle2 },
};

export const PATTERN_LABEL: Record<AgentPattern, string> = {
  PIPELINE_STAGE: "Pipeline stage",
  RETRIEVAL: "Retrieval",
  VALIDATION: "Validation",
  ACTION: "Action (drafts only)",
  COORDINATOR: "Coordinator",
  REVIEWER: "Reviewer",
};

export const TRIGGER_LABEL: Record<TriggerType, string> = {
  NIGHTLY: "Nightly",
  MANUAL_DRY_RUN: "Manual — dry run",
  MANUAL_LIVE: "Manual — live",
  ON_DEMAND: "On demand",
};

export const OUTCOMES: DecisionOutcome[] = [
  "PENDING",
  "ACCEPTED",
  "EDITED",
  "REJECTED",
  "SUPERSEDED",
  "NOT_APPLICABLE",
];
export const RUN_STATUSES: RunStatus[] = [
  "RUNNING",
  "SUCCESS",
  "PARTIAL",
  "FAILED",
  "SKIPPED_DISABLED",
  "SKIPPED_DEPENDENCY",
  "PAUSED",
  "CANCELLED",
];
export const TRIGGER_TYPES: TriggerType[] = ["NIGHTLY", "MANUAL_DRY_RUN", "MANUAL_LIVE", "ON_DEMAND"];

export function decisionLabel(type: string): string {
  const t = type.replaceAll("_", " ").toLowerCase();
  return (t.charAt(0).toUpperCase() + t.slice(1)).replace(/\bpo\b/g, "PO").replace(/\bllm\b/g, "LLM");
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1_000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1_000)} s`;
}

export function formatUsd(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return n === 0 ? "$0" : n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

export function formatRate(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;
}
