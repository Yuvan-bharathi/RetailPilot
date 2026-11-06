import { ShieldCheck, ShieldQuestion, ShieldAlert } from "lucide-react";

import type { ReviewStatus } from "../api/types";
import { StatusBadge } from "./StatusBadge";

/** Recommendation Reviewer label (D-50): "Not reviewed" when the reviewer agent is off or has not run. */
export function ReviewBadge({ status }: { status: ReviewStatus | undefined }) {
  if (status === "REVIEWED") return <StatusBadge tone="success" label="Reviewed" icon={ShieldCheck} />;
  if (status === "FLAGGED") return <StatusBadge tone="warning" label="Reviewer flagged" icon={ShieldAlert} />;
  return <StatusBadge tone="neutral" label="Not reviewed" icon={ShieldQuestion} />;
}
