import type {
  BatchDTO,
  BatchQuery,
  DashboardQuery,
  DashboardSummary,
  ErrorResponse,
  ExpiringQuery,
  InventoryMovementDTO,
  InventoryQuery,
  LoginRequest,
  MeDTO,
  MovementQuery,
  Page,
  PurchaseOrderDTO,
  PurchaseOrderQuery,
  RecommendationDetailDTO,
  RecommendationDTO,
  RecommendationQuery,
  RunInfoDTO,
  StoreDTO,
  StoreInventoryPage,
  TokenResponse,
  TransferOrderDTO,
  TransferQuery,
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
  getStoreInventory(storeId: string, query: InventoryQuery): Promise<StoreInventoryPage>;
  listStoreMovements(storeId: string, query: MovementQuery): Promise<Page<InventoryMovementDTO>>;
  listStoreBatches(storeId: string, query: BatchQuery): Promise<Page<BatchDTO>>;
  listStoreExpiring(storeId: string, query: ExpiringQuery): Promise<Page<BatchDTO>>;
  listTransfers(query: TransferQuery): Promise<Page<TransferOrderDTO>>;
  listPurchaseOrders(query: PurchaseOrderQuery): Promise<Page<PurchaseOrderDTO>>;
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
    getStoreInventory: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory${toQueryString(query)}`),
    listStoreMovements: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory/movements${toQueryString(query)}`),
    listStoreBatches: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory/batches${toQueryString(query)}`),
    listStoreExpiring: (storeId, query) =>
      request("GET", `/stores/${encodeURIComponent(storeId)}/inventory/expiring${toQueryString(query)}`),
    listTransfers: (query) => request("GET", `/transfers${toQueryString(query)}`),
    listPurchaseOrders: (query) => request("GET", `/purchase-orders${toQueryString(query)}`),
  };
}
