import { X } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { Button } from "./Button";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  description?: string;
  /** "drawer" slides in from the right, full height (same focus and keyboard behaviour). */
  variant?: "dialog" | "drawer";
}

/** Accessible dialog: focus moves in and is trapped; Escape closes; focus returns to the opener. */
export function Modal({ open, title, onClose, children, footer, description, variant = "dialog" }: ModalProps) {
  const titleId = useId();
  const descId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel.current)?.focus();
    return () => opener?.focus();
  }, [open]);

  if (!open) return null;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCloseRef.current();
      return;
    }
    if (event.key !== "Tab" || !panel.current) return;
    const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const firstItem = items[0] as HTMLElement;
    const lastItem = items[items.length - 1] as HTMLElement;
    if (event.shiftKey && document.activeElement === firstItem) {
      event.preventDefault();
      lastItem.focus();
    } else if (!event.shiftKey && document.activeElement === lastItem) {
      event.preventDefault();
      firstItem.focus();
    }
  };

  return (
    <div className={`fixed inset-0 z-50 flex ${variant === "drawer" ? "justify-end" : "items-center justify-center p-4"}`}>
      <div aria-hidden="true" className="absolute inset-0 bg-ink/40" onClick={() => onCloseRef.current()} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={
          variant === "drawer"
            ? "relative flex h-full w-full max-w-xl flex-col border-l border-border bg-surface shadow-dropdown"
            : "relative w-full max-w-lg rounded-modal border border-border bg-surface shadow-dropdown"
        }
      >
        <div className="flex items-start justify-between gap-4 border-b border-divider px-5 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-ink">
              {title}
            </h2>
            {description ? (
              <p id={descId} className="mt-1 text-sm text-ink-secondary">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            aria-label="Close"
            className="rounded p-1 text-ink-secondary hover:bg-elevated hover:text-ink"
            onClick={() => onCloseRef.current()}
          >
            <X aria-hidden="true" size={18} />
          </button>
        </div>
        <div className={`px-5 py-4 text-sm text-ink ${variant === "drawer" ? "flex-1 overflow-y-auto" : ""}`}>{children}</div>
        {footer ? <div className="flex justify-end gap-2 border-t border-divider px-5 py-3">{footer}</div> : null}
      </div>
    </div>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** Why the action is being taken (shown first). */
  reason: string;
  /** What will happen if confirmed. */
  consequences: string[];
  /** Who approves next / who is accountable. */
  approver: string;
  confirmLabel: string;
  destructive?: boolean;
  /** Ask the user for a written reason (e.g. rejecting a PO line). */
  requireReason?: boolean;
  onConfirm: (writtenReason: string | null) => void;
  onCancel: () => void;
}

/** Confirmation before a high-impact action: reason, consequences and approver (design doc §3). */
export function ConfirmDialog({
  open,
  title,
  reason,
  consequences,
  approver,
  confirmLabel,
  destructive = false,
  requireReason = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [written, setWritten] = useState("");
  const [touched, setTouched] = useState(false);
  const fieldId = useId();
  const errorId = useId();
  const missing = requireReason && written.trim() === "";

  const close = () => {
    setWritten("");
    setTouched(false);
    onCancel();
  };

  return (
    <Modal
      open={open}
      title={title}
      onClose={close}
      footer={
        <>
          <Button variant="secondary" onClick={close}>
            Cancel
          </Button>
          <Button
            variant={destructive ? "destructive" : "primary"}
            onClick={() => {
              setTouched(true);
              if (missing) return;
              onConfirm(requireReason ? written.trim() : null);
              setWritten("");
              setTouched(false);
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <dl className="space-y-3">
        <div>
          <dt className="text-xs font-medium text-ink-secondary">Reason</dt>
          <dd>{reason}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-ink-secondary">What happens next</dt>
          <dd>
            <ul className="list-disc pl-5">
              {consequences.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-ink-secondary">Approver</dt>
          <dd>{approver}</dd>
        </div>
      </dl>
      {requireReason ? (
        <div className="mt-4">
          <label htmlFor={fieldId} className="text-sm font-medium">
            Your reason <span aria-hidden="true" className="text-danger">*</span>
            <span className="sr-only">(required)</span>
          </label>
          <textarea
            id={fieldId}
            required
            aria-invalid={touched && missing}
            aria-describedby={touched && missing ? errorId : undefined}
            value={written}
            onChange={(e) => setWritten(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-input border border-border p-2 text-sm"
          />
          {touched && missing ? (
            <p id={errorId} className="mt-1 text-xs text-danger">
              Enter a reason before confirming.
            </p>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}
