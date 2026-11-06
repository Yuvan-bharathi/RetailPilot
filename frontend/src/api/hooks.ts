/** TanStack Query hooks (CD-4 QueryHooks). Keys mirror the query so paging/sorting refetch from the server. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useApi } from "../app/ApiContext";
import type {
  AgentRunQuery,
  BatchQuery,
  DashboardQuery,
  DecisionQuery,
  ExpiringQuery,
  InventoryQuery,
  MovementQuery,
  PipelineQuery,
  PurchaseOrderQuery,
  RecommendationQuery,
  RunMode,
  TransferQuery,
} from "./types";

const FIVE_MINUTES = 300_000; // spec §9 React Query staleTime
const POLL_MS = 5_000; // agent console: poll while a run is in progress (docs/09 §3.4)

export function useLatestRun(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ["runs", "latest"],
    queryFn: () => api.getLatestRun(),
    staleTime: FIVE_MINUTES,
    enabled,
  });
}

export function useStores(enabled = true) {
  const api = useApi();
  return useQuery({ queryKey: ["stores"], queryFn: () => api.listStores(), staleTime: FIVE_MINUTES, enabled });
}

export function useDashboard(query: DashboardQuery) {
  const api = useApi();
  return useQuery({ queryKey: ["dashboard", query], queryFn: () => api.getDashboard(query), staleTime: FIVE_MINUTES });
}

export function useDashboardInsights(query: DashboardQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["dashboard-insights", query],
    queryFn: () => api.getDashboardInsights(query),
    staleTime: FIVE_MINUTES,
  });
}

export function useAnalytics(query: DashboardQuery) {
  const api = useApi();
  return useQuery({ queryKey: ["analytics", query], queryFn: () => api.getAnalytics(query), staleTime: FIVE_MINUTES });
}

export function useBusinessRules(enabled = true) {
  const api = useApi();
  return useQuery({ queryKey: ["business-rules"], queryFn: () => api.listBusinessRules(), enabled });
}

export function useRecommendations(query: RecommendationQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["recommendations", query],
    queryFn: () => api.listRecommendations(query),
    placeholderData: keepPreviousData,
  });
}

export function useRecommendation(recId: string) {
  const api = useApi();
  return useQuery({ queryKey: ["recommendation", recId], queryFn: () => api.getRecommendation(recId) });
}

export function useStoreInventory(storeId: string | null, query: InventoryQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["inv", storeId, query],
    queryFn: () => api.getStoreInventory(storeId as string, query),
    enabled: storeId !== null,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useStoreMovements(storeId: string | null, query: MovementQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["inv-moves", storeId, query],
    queryFn: () => api.listStoreMovements(storeId as string, query),
    enabled: storeId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useStoreBatches(storeId: string | null, query: BatchQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["inv-batches", storeId, query],
    queryFn: () => api.listStoreBatches(storeId as string, query),
    enabled: storeId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useStoreExpiring(storeId: string | null, query: ExpiringQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["inv-expiring", storeId, query],
    queryFn: () => api.listStoreExpiring(storeId as string, query),
    enabled: storeId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useTransfers(query: TransferQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["transfers", query],
    queryFn: () => api.listTransfers(query),
    placeholderData: keepPreviousData,
  });
}

export function usePurchaseOrders(query: PurchaseOrderQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["purchase-orders", query],
    queryFn: () => api.listPurchaseOrders(query),
    placeholderData: keepPreviousData,
  });
}

export function usePurchaseOrder(poId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ["purchase-order", poId],
    queryFn: () => api.getPurchaseOrder(poId as string),
    enabled: poId !== null,
  });
}

export function useTransfer(transferId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ["transfer", transferId],
    queryFn: () => api.getTransfer(transferId as string),
    enabled: transferId !== null,
  });
}

export function useNotifications(unreadOnly = false) {
  const api = useApi();
  return useQuery({
    queryKey: ["notifications", unreadOnly],
    queryFn: () => api.listNotifications(unreadOnly),
    staleTime: 30_000,
  });
}

export function useAgents() {
  const api = useApi();
  return useQuery({ queryKey: ["agents"], queryFn: () => api.listAgents(), staleTime: 15_000 });
}

export function useAgent(agentKey: string) {
  const api = useApi();
  return useQuery({ queryKey: ["agent", agentKey], queryFn: () => api.getAgent(agentKey) });
}

export function useAgentStats(agentKey: string) {
  const api = useApi();
  return useQuery({ queryKey: ["agent-stats", agentKey], queryFn: () => api.getAgentStats(agentKey) });
}

export function useTriggerPreview(agentKey: string, mode: RunMode, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ["trigger-preview", agentKey, mode],
    queryFn: () => api.getTriggerPreview(agentKey, mode),
    enabled,
    staleTime: 0,
  });
}

/** Runs list; polls every 5 s while a listed run is RUNNING (docs/09 §3.4). */
export function useAgentRuns(query: AgentRunQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["agent-runs", query],
    queryFn: () => api.listAgentRuns(query),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "RUNNING") ? POLL_MS : false),
  });
}

export function useAgentRun(runId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ["agent-run", runId],
    queryFn: () => api.getAgentRun(runId as string),
    enabled: runId !== null,
    refetchInterval: (q) => (q.state.data?.run.status === "RUNNING" ? POLL_MS : false),
  });
}

export function useDecisions(query: DecisionQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["agent-decisions", query],
    queryFn: () => api.listDecisions(query),
    placeholderData: keepPreviousData,
  });
}

export function useDecisionStats(agentKey?: string) {
  const api = useApi();
  return useQuery({ queryKey: ["decision-stats", agentKey ?? null], queryFn: () => api.getDecisionStats(agentKey) });
}

export function usePipelineRuns(query: PipelineQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["pipeline-runs", query],
    queryFn: () => api.listPipelineRuns(query),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "RUNNING") ? POLL_MS : false),
  });
}

/** Visual flow graph; polls every 5 s while the run is in progress (docs/09 §3.4). */
export function useRunGraph(runId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ["run-graph", runId],
    queryFn: () => api.getRunGraph(runId as string),
    enabled: runId !== null,
    refetchInterval: (q) => (q.state.data?.in_progress ? POLL_MS : false),
  });
}

export function useAssistantStatus() {
  const api = useApi();
  return useQuery({ queryKey: ["assistant-status"], queryFn: () => api.getAssistantStatus() });
}

/** Agent-switch banners for every role (expiry checks off, replenishment paused) — D-54. */
export function useAgentStatus() {
  const api = useApi();
  return useQuery({ queryKey: ["agent-status"], queryFn: () => api.getAgentStatus(), staleTime: 60_000 });
}
