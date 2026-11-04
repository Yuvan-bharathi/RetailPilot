import {
  ArrowRight,
  Building2,
  CheckCircle2,
  MapPin,
  Search,
  ShoppingBag,
  Store as StoreIcon,
  Warehouse,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { useStores } from "../api/hooks";
import { useAuth } from "../app/AuthContext";
import { useShell } from "../app/ShellContext";

export function StoresPage() {
  const { user } = useAuth();
  const { setStoreId } = useShell();
  const navigate = useNavigate();
  const isAdmin = user?.role === "SUPER_ADMIN";
  const storesQuery = useStores(isAdmin);
  const [searchTerm, setSearchTerm] = useState("");
  const [regionFilter, setRegionFilter] = useState("ALL");

  const stores = storesQuery.data ?? [];

  const regions = Array.from(new Set(stores.map((s) => s.region).filter(Boolean))).sort();

  const filteredStores = stores.filter((s) => {
    const matchesRegion = regionFilter === "ALL" || s.region === regionFilter;
    const matchesSearch =
      searchTerm === "" ||
      s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.code.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (s.region && s.region.toLowerCase().includes(searchTerm.toLowerCase()));
    return matchesRegion && matchesSearch;
  });

  const handleSelectStore = (storeId: string) => {
    setStoreId(storeId);
    navigate("/inventory");
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-ink">Retail Store Network</h2>
          <p className="mt-1 text-sm text-ink-secondary">
            Manage store locations, supervise store-level stock replenishment, and switch operational contexts.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-success-bg px-3 py-1 text-xs font-semibold text-success">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {stores.length} Active Outlets
          </span>
        </div>
      </div>

      {/* Network Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Total Locations</span>
            <div className="rounded-card bg-brand-soft p-2 text-brand">
              <Building2 className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-3xl font-bold text-ink tabular">{stores.length}</div>
          <div className="mt-1 text-xs text-ink-secondary">Supervised chain outlets</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">Regional Hubs</span>
            <div className="rounded-card bg-info-bg p-2 text-info">
              <MapPin className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-3xl font-bold text-ink tabular">{regions.length || 1}</div>
          <div className="mt-1 text-xs text-ink-secondary">Metro clusters</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Replenishment Mode
            </span>
            <div className="rounded-card bg-success-bg p-2 text-success">
              <Warehouse className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 text-2xl font-bold text-success">Autonomous AI</div>
          <div className="mt-1 text-xs text-ink-secondary">Nightly agent reordering enabled</div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface p-3 shadow-card">
        <div className="flex flex-1 items-center gap-2 min-w-[240px]">
          <Search className="h-4 w-4 text-ink-secondary" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search stores by name, code or region…"
            className="w-full bg-transparent text-sm text-ink placeholder:text-ink-disabled focus:outline-none"
          />
        </div>

        {regions.length > 0 && (
          <div className="flex items-center gap-2">
            <select
              value={regionFilter}
              onChange={(e) => setRegionFilter(e.target.value)}
              className="h-8 rounded-input border border-border bg-surface px-2.5 text-xs text-ink focus:outline-none"
            >
              <option value="ALL">All Regions</option>
              {regions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Stores Grid */}
      {storesQuery.isLoading ? (
        <div className="py-12 text-center text-ink-secondary">Loading store directory…</div>
      ) : filteredStores.length === 0 ? (
        <div className="rounded-card border border-border bg-surface p-12 text-center text-ink-secondary shadow-card">
          No stores found matching your criteria.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
          {filteredStores.map((store) => (
            <div
              key={store.store_id}
              className="flex flex-col justify-between rounded-card border border-border bg-surface p-5 shadow-card transition-shadow hover:shadow-dropdown"
            >
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-10 w-10 items-center justify-center rounded-card bg-brand-soft text-brand">
                      <StoreIcon className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="font-bold text-ink">{store.name}</h3>
                      <span className="font-mono text-xs text-ink-secondary font-medium">Code: {store.code}</span>
                    </div>
                  </div>
                  <span className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold text-brand">
                    {store.store_type || "Supermarket"}
                  </span>
                </div>

                <div className="mt-4 space-y-2 border-t border-border pt-4 text-xs text-ink-secondary">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5 text-ink-secondary" />
                      Region
                    </span>
                    <span className="font-medium text-ink">{store.region || "Central"}</span>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5">
                      <ShoppingBag className="h-3.5 w-3.5 text-ink-secondary" />
                      Status
                    </span>
                    <span className="inline-flex items-center gap-1 text-success font-medium">
                      <span className="h-1.5 w-1.5 rounded-full bg-success" />
                      Operational
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-6 border-t border-border pt-4">
                <button
                  type="button"
                  onClick={() => handleSelectStore(store.store_id)}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-button bg-elevated px-4 py-2 text-xs font-semibold text-ink border border-border hover:bg-brand hover:text-surface hover:border-brand transition-colors"
                >
                  Manage Store Inventory
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
