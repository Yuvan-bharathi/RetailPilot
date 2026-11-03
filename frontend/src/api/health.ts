import { useQuery } from "@tanstack/react-query";

import type { components } from "./schema";

// DTO types come from the generated OpenAPI schema (npm run gen:api) — never hand-written.
export type HealthResponse = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/health");
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: fetchHealth, staleTime: 30_000 });
}
