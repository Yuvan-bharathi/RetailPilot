/**
 * Mock data exported from the synthetic `small` dataset by backend/scripts/export_mock_fixtures.py, which runs the
 * real Phase 3 tools and validates every object against the backend DTOs. Regenerate with:
 *   cd backend && uv run python -m scripts.export_mock_fixtures
 * The shape below is composed only of generated DTO types (no hand-written DTO shapes).
 */
import rawFixtures from "./data/fixtures.json";

import type {
  BatchDTO,
  DashboardInsights,
  DashboardSummary,
  Evidence,
  InventoryMovementDTO,
  InventoryRowDTO,
  PurchaseOrderDTO,
  RecommendationDTO,
  Role,
  RunInfoDTO,
  StoreDTO,
  TransferOrderDTO,
} from "../api/types";

export interface MockUser {
  username: string;
  user_id: string;
  name: string;
  role: Role;
  store_id: string | null;
}

export interface ScenarioIndex {
  title: string;
  product_id: string;
  rec_ids: string[];
}

export interface MockFixtures {
  generated: { source: string; seed: number; profile: string; run_date: string; note: string };
  stores: StoreDTO[];
  users: MockUser[];
  latest_run: RunInfoDTO;
  /** keyed by store_id */
  inventory: Record<string, InventoryRowDTO[]>;
  movements: Record<string, InventoryMovementDTO[]>;
  batches: Record<string, BatchDTO[]>;
  recommendations: RecommendationDTO[];
  /** keyed by rec_id; full (Super Admin) view — the mock client scopes it per viewer */
  evidence: Record<string, Evidence>;
  transfers: TransferOrderDTO[];
  purchase_orders: PurchaseOrderDTO[];
  /** keyed by store_id, plus "all" */
  dashboard: Record<string, DashboardSummary>;
  dashboard_insights: Record<string, DashboardInsights>;
  scenarios: Record<"1" | "2" | "3" | "4" | "5", ScenarioIndex>;
}

export const FIXTURES = rawFixtures as unknown as MockFixtures;
export const MOCK_PASSWORD = "demo";
