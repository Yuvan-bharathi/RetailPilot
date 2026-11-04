import { Inbox, RefreshCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./Button";

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <Inbox aria-hidden="true" className="text-ink-secondary" size={28} />
      <p className="font-semibold text-ink">{title}</p>
      {description ? <p className="max-w-md text-sm text-ink-secondary">{description}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <TriangleAlert aria-hidden="true" className="text-danger" size={28} />
      <p className="font-semibold text-ink">Could not load data</p>
      <p className="max-w-md text-sm text-ink-secondary">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function SkeletonLine({ width = "100%" }: { width?: string }) {
  return <span aria-hidden="true" className="block h-3 animate-pulse rounded bg-divider" style={{ width }} />;
}
