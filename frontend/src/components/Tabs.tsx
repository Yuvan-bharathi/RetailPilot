import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface TabItem {
  key: string;
  label: ReactNode;
}

/**
 * WAI-ARIA tabs: one tab in the Tab order (roving tabindex), Arrow Left/Right move between tabs, Home/End jump,
 * selection follows focus. The panel is focusable so keyboard users can reach its content.
 */
export function Tabs({
  label,
  items,
  value,
  onChange,
  children,
}: {
  label: string;
  items: TabItem[];
  value: string;
  onChange: (key: string) => void;
  children: ReactNode;
}) {
  const id = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const index = Math.max(0, items.findIndex((t) => t.key === value));

  const select = (i: number) => {
    const item = items[(i + items.length) % items.length];
    if (!item) return;
    onChange(item.key);
    refs.current[item.key]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: items.length - 1 };
    const next = moves[event.key];
    if (next === undefined) return;
    event.preventDefault();
    select(next);
  };

  return (
    <div>
      <div role="tablist" aria-label={label} onKeyDown={onKeyDown} className="flex gap-1 border-b border-border">
        {items.map((item) => {
          const selected = item.key === value;
          return (
            <button
              key={item.key}
              ref={(el) => {
                refs.current[item.key] = el;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${item.key}`}
              aria-selected={selected}
              aria-controls={`${id}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(item.key)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${
                selected ? "border-brand font-semibold text-brand" : "border-transparent text-ink-secondary hover:text-ink"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${value}`} tabIndex={0} className="pt-4">
        {children}
      </div>
    </div>
  );
}
