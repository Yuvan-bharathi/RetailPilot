import type {
  AgentRunDetailDTO,
  ApprovalRequest,
  ApprovalResult,
  BatchDTO,
  BatchQuery,
  CloseShortRequest,
  CursorPage,
  DashboardQuery,
  DashboardSummary,
  ErrorResponse,
  ExpiringQuery,
  GoodsReceiptRequest,
  InventoryMovementDTO,
  InventoryQuery,
  LoginRequest,
  MeDTO,
  MovementQuery,
  NotificationDTO,
  Page,
  PurchaseOrderDTO,
  PurchaseOrderQuery,
  RecActionRequest,
  RecommendationDetailDTO,
  RecommendationDTO,
  RecommendationQuery,
  ResolvePORequest,
  RunInfoDTO,
  StoreDTO,
  StoreInventoryPage,
  TokenResponse,
  TransferOrderDTO,
  TransferQuery,
  TriggerRunRequest,
} from "./types";

/** Every call the UI makes, typed by the generated OpenAPI contract. */
export interface ApiClient {
  login(body: LoginRequest): Promise<TokenResponse>;
  getMe(): Promise<MeDTO>;
  listStores(): Promise<StoreDTO[]>;
  getLatestRun(): Promise<RunInfoDTO>;
  getDashboard(query: DashboardQuery): Promise<DashboardSummary>;
  listRecommendations(query: RecommendationQuery): Promise<Page<RecommendationDTO>>;
  getRecommendation(recId: string): Promise<RecommendationDetailDTO>;
  actOnRecommendation(recId: string, body: RecActionRequest): Promise<RecommendationDTO>;
  getStoreInventory(storeId: string, query: InventoryQuery): Promise<StoreInventoryPage>;
  listStoreMovements(storeId: string, query: MovementQuery): Promise<CursorPage<InventoryMovementDTO>>;
  listStoreBatches(storeId: string, query: BatchQuery): Promise<Page<BatchDTO>>;
  listStoreExpiring(storeId: string, query: ExpiringQuery): Promise<Page<BatchDTO>>;
  listTransfers(query: TransferQuery): Promise<Page<TransferOrderDTO>>;
  getTransfer(transferId: string): Promise<TransferOrderDTO>;
  acceptTransfer(transferId: string): Promise<TransferOrderDTO>;
  approveReleaseTransfer(transferId: string): Promise<TransferOrderDTO>;
  rejectTransfer(transferId: string, reason: string): Promise<TransferOrderDTO>;
  dispatchTransfer(transferId: string): Promise<TransferOrderDTO>;
  receiveTransfer(transferId: string, receivedQty: number): Promise<TransferOrderDTO>;
  listPurchaseOrders(query: PurchaseOrderQuery): Promise<Page<PurchaseOrderDTO>>;
  getPurchaseOrder(poId: string): Promise<PurchaseOrderDTO>;
  createApproval(body: ApprovalRequest): Promise<ApprovalResult>;
  receiveGoods(poId: string, body: GoodsReceiptRequest): Promise<PurchaseOrderDTO>;
  resolvePurchaseOrder(poId: string, body: ResolvePORequest): Promise<PurchaseOrderDTO>;
  closeShortPurchaseOrder(poId: string, body: CloseShortRequest): Promise<PurchaseOrderDTO>;
  listNotifications(unreadOnly?: boolean): Promise<NotificationDTO[]>;
  markNotificationRead(id: string): Promise<NotificationDTO>;
  listAgentRuns(limit?: number): Promise<AgentRunDetailDTO[]>;
  getAgentRun(runId: string): Promise<AgentRunDetailDTO>;
  triggerNightlyRun(body?: TriggerRunRequest): Promise<{ message: string; run_id?: string; run_date: string }>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type QueryValue = string | number | boolean | null | undefined;

export function toQueryString(query: Record<string, QueryValue> | undefined): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Real backend client (FastAPI, /api/v1, JWT bearer). */
export function createHttpClient(getToken: () => string | null, baseUrl = "/api/v1"): ApiClient {
  async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const token = getToken();
    const response = await fetch(`${baseUrl}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null;
      throw new ApiError(
        response.status,
        payload?.error.code ?? "INTERNAL",
        payload?.error.message ?? response.statusText,
      );
    }
    return (await response.json()) as T;
  }

  return {
    login: (body) => request("POST", "/auth/login", body),
    getMe: () => request("GET", "/me"),
    listStores: () => request("GET", "/stores"),
    getLatestRun: () => request("GET", "/runs/latest"),
    getDashboard: (query) => request("GET", `/dashboard${toQueryString(query)}`),
    listRecommendations: (query) => request("GET", `/recommendations${toQueryString(query)}`),
    getRecommendation: (recId) => request("GET", `/recommendations/${encodeURIComponent(recId)}`),
    actOnRecommendation: (recId, body) => request("POST", `/recommendations/${encodeURIComponent(recId)}/action`, body),
    getStoreInventory: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory${toQueryString(query)}`),
    listStoreMovements: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory/movements${toQueryString(query)}`),
    listStoreBatches: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory/batches${toQueryString(query)}`),
    listStoreExpiring: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory/expiring${toQueryString(query)}`),
    listTransfers: (query) => request("GET", `/transfers${toQueryString(query)}`),
    getTransfer: (transferId) => request("GET", `/transfers/${encodeURIComponent(transferId)}`),
    acceptTransfer: (transferId) => request("POST", `/transfers/${encodeURIComponent(transferId)}/accept`),
    approveReleaseTransfer: (transferId) =>
      request("POST", `/transfers/${encodeURIComponent(transferId)}/approve-release`),
    rejectTransfer: (transferId, reason) =>
      request("POST", `/transfers/${encodeURIComponent(transferId)}/reject`, { reason }),
    dispatchTransfer: (transferId) => request("POST", `/transfers/${encodeURIComponent(transferId)}/dispatch`),
    receiveTransfer: (transferId, receivedQty) =>
      request("POST", `/transfers/${encodeURIComponent(transferId)}/receive`, { received_qty: receivedQty }),
    listPurchaseOrders: (query) => request("GET", `/purchase-orders${toQueryString(query)}`),
    getPurchaseOrder: (poId) => request("GET", `/purchase-orders/${encodeURIComponent(poId)}`),
    createApproval: (body) => request("POST", "/approvals", body),
    receiveGoods: (poId, body) => request("POST", `/purchase-orders/${encodeURIComponent(poId)}/receipts`, body),
    resolvePurchaseOrder: (poId, body) => request("POST", `/purchase-orders/${encodeURIComponent(poId)}/resolve`, body),
    closeShortPurchaseOrder: (poId, body) =>
      request("POST", `/purchase-orders/${encodeURIComponent(poId)}/close-short`, body),
    listNotifications: (unreadOnly) =>
      request("GET", `/notifications${toQueryString(unreadOnly ? { unread: true } : undefined)}`),
    markNotificationRead: (id) => request("POST", `/notifications/${encodeURIComponent(id)}/read`),
    listAgentRuns: (limit) => request("GET", `/agent-runs${toQueryString(limit ? { limit } : undefined)}`),
    getAgentRun: (runId) => request("GET", `/agent-runs/${encodeURIComponent(runId)}`),
    triggerNightlyRun: (body) => request("POST", "/admin/runs", body ?? {}),
  };
}
