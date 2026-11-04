import { AlertTriangle, CheckCircle2, Circle, Clock, Info, OctagonAlert, type LucideIcon } from "lucide-react";

export type Tone = "success" | "warning" | "attention" | "danger" | "info" | "neutral";

const TONE: Record<Tone, { classes: string; icon: LucideIcon }> = {
  success: { classes: "bg-success-bg text-success", icon: CheckCircle2 },
  warning: { classes: "bg-warning-bg text-warning", icon: AlertTriangle },
  attention: { classes: "bg-attention-bg text-attention", icon: Clock },
  danger: { classes: "bg-danger-bg text-danger", icon: OctagonAlert },
  info: { classes: "bg-info-bg text-info", icon: Info },
  neutral: { classes: "bg-neutral-bg text-neutral", icon: Circle },
};

/** Status chip: semantic colour + icon + text label — never colour alone (design doc §3, §7). */
export function StatusBadge({ tone, label, icon }: { tone: Tone; label: string; icon?: LucideIcon }) {
  const style = TONE[tone];
  const Icon = icon ?? style.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${style.classes}`}
    >
      <Icon aria-hidden="true" size={12} strokeWidth={2.25} />
      {label}
    </span>
  );
}

const STATUS: Record<string, { tone: Tone; label: string }> = {
  // recommendations
  PENDING: { tone: "info", label: "Pending" },
  ACCEPTED: { tone: "success", label: "Accepted" },
  EDITED: { tone: "success", label: "Edited" },
  REJECTED: { tone: "danger", label: "Rejected" },
  NEEDS_REVIEW: { tone: "warning", label: "Needs review" },
  SUPERSEDED: { tone: "neutral", label: "Superseded" },
  // purchase orders / lines
  DRAFT: { tone: "neutral", label: "Draft" },
  PENDING_L1: { tone: "info", label: "Pending L1" },
  PENDING_L2: { tone: "info", label: "Pending L2" },
  APPROVED: { tone: "success", label: "Approved" },
  SPLIT: { tone: "attention", label: "Split" },
  SUBMITTED: { tone: "info", label: "Submitted" },
  RECEIVED: { tone: "success", label: "Received" },
  EXPIRED: { tone: "danger", label: "Expired" },
  ESCALATED: { tone: "attention", label: "Escalated" },
  // transfers
  PROPOSED: { tone: "info", label: "Proposed" },
  DEST_ACCEPTED: { tone: "info", label: "Destination accepted" },
  DONOR_APPROVED: { tone: "info", label: "Donor approved" },
  DISPATCHED: { tone: "attention", label: "Dispatched" },
  CANCELLED: { tone: "neutral", label: "Cancelled" },
  // stockout risk
  HIGH: { tone: "danger", label: "High" },
  MEDIUM: { tone: "warning", label: "Medium" },
  LOW: { tone: "success", label: "Low" },
};

// eslint-disable-next-line react-refresh/only-export-components
export function statusDisplay(status: string): { tone: Tone; label: string } {
  return STATUS[status] ?? { tone: "neutral", label: status.replaceAll("_", " ").toLowerCase() };
}

export function StatusPill({ status }: { status: string }) {
  const { tone, label } = statusDisplay(status);
  return <StatusBadge tone={tone} label={label} />;
}
