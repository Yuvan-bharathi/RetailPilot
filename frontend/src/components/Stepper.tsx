import { Check, X } from "lucide-react";

export interface Step {
  key: string;
  label: string;
}

/** Transfer execution steps (design doc §6 / SD-12). */
// eslint-disable-next-line react-refresh/only-export-components
export const TRANSFER_STEPS: Step[] = [
  { key: "PROPOSED", label: "Proposed" },
  { key: "DEST_ACCEPTED", label: "Destination accepted" },
  { key: "DONOR_APPROVED", label: "Donor approved" },
  { key: "DISPATCHED", label: "Dispatched" },
  { key: "RECEIVED", label: "Received" },
];

/**
 * Horizontal stepper. `current` is the step reached; `failed` marks the flow as stopped at that step
 * (rejected / cancelled); `note` adds a line under the last step (e.g. a discrepancy).
 */
export function Stepper({
  steps,
  current,
  failed,
  note,
  label = "Progress",
}: {
  steps: Step[];
  current: string;
  failed?: { label: string };
  note?: string;
  label?: string;
}) {
  const index = Math.max(
    0,
    steps.findIndex((s) => s.key === current),
  );
  return (
    <nav aria-label={label}>
      <ol className="flex flex-wrap items-start gap-y-3">
        {steps.map((step, i) => {
          const done = i < index || (i === index && !failed && i === steps.length - 1);
          const isCurrent = i === index;
          const isFailed = isCurrent && failed !== undefined;
          const circle = isFailed
            ? "border-danger bg-danger-bg text-danger"
            : done
              ? "border-brand bg-brand text-surface"
              : isCurrent
                ? "border-brand bg-brand-soft text-brand"
                : "border-border bg-surface text-ink-secondary";
          return (
            <li
              key={step.key}
              className="flex min-w-[120px] flex-1 items-start"
              aria-current={isCurrent ? "step" : undefined}
            >
              <div className="flex flex-col items-center gap-1 text-center">
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full border-2 text-xs font-semibold ${circle}`}
                >
                  {isFailed ? (
                    <X aria-hidden="true" size={14} />
                  ) : done ? (
                    <Check aria-hidden="true" size={14} />
                  ) : (
                    i + 1
                  )}
                </span>
                <span className={`text-xs ${isCurrent ? "font-semibold text-ink" : "text-ink-secondary"}`}>
                  {step.label}
                  {isFailed ? <span className="block text-danger">{failed.label}</span> : null}
                  {done ? <span className="sr-only"> (completed)</span> : null}
                </span>
              </div>
              {i < steps.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={`mx-2 mt-3.5 h-0.5 flex-1 ${i < index ? "bg-brand" : "bg-border"}`}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
      {note ? <p className="mt-2 text-xs text-attention">{note}</p> : null}
    </nav>
  );
}
