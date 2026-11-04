/** TanStack Query hooks (CD-4 QueryHooks). Keys mirror the query so paging/sorting refetch from the server. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useApi } from "../app/ApiContext";
import type {
  BatchQuery,
  DashboardQuery,
  ExpiringQuery,
  InventoryQuery,
  MovementQuery,
  PurchaseOrderQuery,
  RecommendationQuery,
  TransferQuery,
} from "./types";

const FIVE_MINUTES = 300_000; // spec §9 React Query staleTime

export function useLatestRun(enabled = true) {
  const api = useApi();
  return useQuery({ queryKey: ["runs", "latest"], queryFn: () => api.getLatestRun(), staleTime: FIVE_MINUTES, enabled });
}

export function useStores(enabled = true) {
  const api = useApi();
  return useQuery({ queryKey: ["stores"], queryFn: () => api.listStores(), staleTime: FIVE_MINUTES, enabled });
}

export function useDashboard(query: DashboardQuery) {
  const api = useApi();
  return useQuery({ queryKey: ["dashboard", query], queryFn: () => api.getDashboard(query), staleTime: FIVE_MINUTES });
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
  return useQuery({ queryKey: ["transfers", query], queryFn: () => api.listTransfers(query), placeholderData: keepPreviousData });
}

export function usePurchaseOrders(query: PurchaseOrderQuery) {
  const api = useApi();
  return useQuery({
    queryKey: ["purchase-orders", query],
    queryFn: () => api.listPurchaseOrders(query),
    placeholderData: keepPreviousData,
  });
}
