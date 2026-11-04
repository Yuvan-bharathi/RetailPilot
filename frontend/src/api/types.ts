/**
 * Short names for the generated OpenAPI types (src/api/schema.d.ts, `npm run gen:api`).
 * These are aliases only — DTO shapes are never written by hand (CLAUDE.md).
 */
import type { components, operations } from "./schema";

type Schemas = components["schemas"];

export type StoreRef = Schemas["StoreRef"];
export type ProductRef = Schemas["ProductRef"];
export type Counterpart = Schemas["Counterpart"];
export type ErrorResponse = Schemas["ErrorResponse"];

export type LoginRequest = Schemas["LoginRequest"];
export type TokenResponse = Schemas["TokenResponse"];
export type MeDTO = Schemas["MeDTO"];
export type Role = MeDTO["role"];
export type StoreDTO = Schemas["StoreDTO"];
export type RunInfoDTO = Schemas["RunInfoDTO"];

export type DashboardSummary = Schemas["DashboardSummary"];
export type Period = DashboardSummary["period"];
export type MoverDTO = Schemas["MoverDTO"];

export type RecommendationDTO = Schemas["RecommendationDTO"];
export type RecommendationDetailDTO = Schemas["RecommendationDetailDTO"];
export type TransferEvidenceDTO = Schemas["TransferEvidenceDTO"];
export type RecType = RecommendationDTO["rec_type"];
export type RecStatus = RecommendationDTO["status"];

export type InventoryRowDTO = Schemas["InventoryRowDTO"];
export type TransferOrderDTO = Schemas["TransferOrderDTO"];
export type TransferStatus = TransferOrderDTO["status"];
export type PurchaseOrderDTO = Schemas["PurchaseOrderDTO"];
export type POLineDTO = Schemas["POLineDTO"];
export type POStatus = PurchaseOrderDTO["status"];
export type LineStatus = POLineDTO["line_status"];

/** Page[T] (backend generic) — derived from a generated page type, with the item type swapped in. */
export type Page<T> = Omit<Schemas["Page_RecommendationDTO_"], "items"> & { items: T[] };

type Query<Op extends keyof operations> = NonNullable<operations[Op]["parameters"]["query"]>;
export type RecommendationQuery = Query<"list_recommendations">;
export type InventoryQuery = Query<"get_store_inventory">;
export type TransferQuery = Query<"list_transfers">;
export type PurchaseOrderQuery = Query<"list_purchase_orders">;
export type DashboardQuery = Query<"get_dashboard">;
/** page, page_size, sort ("field" or "-field"), q — shared by every list endpoint (PageParams). */
export type PageQuery = Pick<RecommendationQuery, "page" | "page_size" | "sort" | "q">;
