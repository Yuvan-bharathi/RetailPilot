import { AlarmClock, Clock, OctagonAlert, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { formatDateTimeIST } from "../lib/format";
import { StatusBadge } from "./StatusBadge";

const DUE_SOON_MS = 2 * 60 * 60 * 1000;

function duration(ms: number): string {
  const minutes = Math.floor(Math.abs(ms) / 60_000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${String(mins).padStart(2, "0")}m`;
  return `${mins}m`;
}

export type DeadlineState = "on-time" | "due-soon" | "overdue" | "escalated";

// eslint-disable-next-line react-refresh/only-export-components
export function deadlineState(deadline: string, now: number, escalated: boolean): DeadlineState {
  if (escalated) return "escalated";
  const left = new Date(deadline).getTime() - now;
  if (left < 0) return "overdue";
  return left <= DUE_SOON_MS ? "due-soon" : "on-time";
}

/** L1 approval deadline: countdown, due soon, overdue and escalated states (design doc §6, SD-14). */
export function DeadlineCountdown({
  deadline,
  escalated = false,
  now,
}: {
  deadline: string;
  escalated?: boolean;
  now?: number;
}) {
  const [tick, setTick] = useState(() => now ?? Date.now());

  useEffect(() => {
    if (now !== undefined) return;
    const timer = setInterval(() => setTick(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, [now]);

  const current = now ?? tick;
  const state = deadlineState(deadline, current, escalated);
  const left = new Date(deadline).getTime() - current;
  const title = `L1 deadline ${formatDateTimeIST(deadline)}`;

  switch (state) {
    case "escalated":
      return (
        <span title={title}>
          <StatusBadge tone="attention" icon={TriangleAlert} label="Escalated to Super Admin" />
        </span>
      );
    case "overdue":
      return (
        <span title={title}>
          <StatusBadge tone="danger" icon={OctagonAlert} label={`Overdue by ${duration(left)}`} />
        </span>
      );
    case "due-soon":
      return (
        <span title={title}>
          <StatusBadge tone="warning" icon={AlarmClock} label={`Due in ${duration(left)}`} />
        </span>
      );
    default:
      return (
        <span title={title}>
          <StatusBadge tone="info" icon={Clock} label={`Due in ${duration(left)}`} />
        </span>
      );
  }
}
