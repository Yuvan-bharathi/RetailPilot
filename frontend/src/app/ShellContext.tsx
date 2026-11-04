import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { Period } from "../api/types";

interface ShellState {
  /** Super Admin's store switcher selection; null = all stores. Supervisors are pinned to their store. */
  storeId: string | null;
  setStoreId(id: string | null): void;
  period: Period;
  setPeriod(p: Period): void;
}

const ShellContext = createContext<ShellState | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [storeId, setStoreId] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>("LAST_28_DAYS");
  const value = useMemo(() => ({ storeId, setStoreId, period, setPeriod }), [storeId, period]);
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useShell(): ShellState {
  const state = useContext(ShellContext);
  if (!state) throw new Error("useShell must be used inside <ShellProvider>");
  return state;
}
