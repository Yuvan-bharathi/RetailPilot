import { createContext, useContext, type ReactNode } from "react";

import type { ApiClient } from "../api/client";

const ApiContext = createContext<ApiClient | null>(null);

/** Provides the API client (real or mock); tests inject their own. */
export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error("useApi must be used inside <ApiProvider>");
  return client;
}
