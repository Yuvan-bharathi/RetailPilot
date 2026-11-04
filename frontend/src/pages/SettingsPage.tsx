import { useState } from "react";
import { CheckCircle2, Coins, Save, Sliders, UserCheck } from "lucide-react";

import { useAuth } from "../app/AuthContext";

export function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "SUPER_ADMIN";

  const [saved, setSaved] = useState(false);
  const [formData, setFormData] = useState({
    safetyStockDaysPerishable: 3,
    safetyStockDaysStaples: 7,
    serviceLevelTarget: 95.0,
    fastMoverWeeklyVelocity: 50,
    minBillCount: 30,
    minBasketLift: 1.5,
    minBasketConfidence: 20.0,
    holdingCostRatePerDay: 0.05,
    orderFixedCost: 250,
    approvalCutoffHourIST: "16:00",
    nightlyPipelineHourIST: "00:00",
    autoEscalateL2: true,
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight text-ink">
              {isAdmin ? "System Configuration & Business Rules" : "User Profile & Store Preferences"}
            </h1>
            <span className="rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-semibold text-brand">
              {isAdmin ? "L2 Super Admin" : "L1 Store Supervisor"}
            </span>
          </div>
          <p className="text-sm text-ink-secondary">
            Manage replenishment heuristics, inventory holding costs, approval deadlines, and session parameters.
          </p>
        </div>

        {saved && (
          <div className="flex items-center gap-2 rounded-card border border-success-bg bg-success-bg/60 px-3 py-1.5 text-xs font-medium text-success">
            <CheckCircle2 className="h-4 w-4" />
            <span>Settings saved successfully!</span>
          </div>
        )}
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Section 1: Replenishment Thresholds */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center gap-2 border-b border-divider pb-3">
            <Sliders className="h-4 w-4 text-brand" />
            <h2 className="text-base font-semibold text-ink">Replenishment Engine Parameters</h2>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-ink-secondary">Safety Stock Buffer (Perishables)</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="number"
                  disabled={!isAdmin}
                  value={formData.safetyStockDaysPerishable}
                  onChange={(e) => setFormData({ ...formData, safetyStockDaysPerishable: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">days</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Dairy, bread, and fresh greens</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">
                Safety Stock Buffer (Staples & FMCG)
              </label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="number"
                  disabled={!isAdmin}
                  value={formData.safetyStockDaysStaples}
                  onChange={(e) => setFormData({ ...formData, safetyStockDaysStaples: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">days</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Rice, oils, and packaged staples</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">Target Stock Availability Rate</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="number"
                  step="0.5"
                  disabled={!isAdmin}
                  value={formData.serviceLevelTarget}
                  onChange={(e) => setFormData({ ...formData, serviceLevelTarget: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">%</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Target service level (Z-score calculation)</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">Fast Mover Threshold</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="number"
                  disabled={!isAdmin}
                  value={formData.fastMoverWeeklyVelocity}
                  onChange={(e) => setFormData({ ...formData, fastMoverWeeklyVelocity: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">
                  units/wk
                </span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Minimum sales velocity to qualify as Class A</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">Co-Replenishment Minimum Lift</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="number"
                  step="0.1"
                  disabled={!isAdmin}
                  value={formData.minBasketLift}
                  onChange={(e) => setFormData({ ...formData, minBasketLift: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">ratio</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Association rule bundle requirement</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">
                Co-Replenishment Minimum Confidence
              </label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="number"
                  step="1"
                  disabled={!isAdmin}
                  value={formData.minBasketConfidence}
                  onChange={(e) => setFormData({ ...formData, minBasketConfidence: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">%</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Basket pairing confidence threshold</p>
            </div>
          </div>
        </div>

        {/* Section 2: Financial & Operational Cost Parameters */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center gap-2 border-b border-divider pb-3">
            <Coins className="h-4 w-4 text-brand" />
            <h2 className="text-base font-semibold text-ink">Holding & Fixed Order Economics</h2>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-ink-secondary">Holding Cost Rate (per unit / day)</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <span className="flex items-center border-r border-divider px-3 text-xs text-ink-secondary">₹</span>
                <input
                  type="number"
                  step="0.01"
                  disabled={!isAdmin}
                  value={formData.holdingCostRatePerDay}
                  onChange={(e) => setFormData({ ...formData, holdingCostRatePerDay: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Used in inter-store balancing trade-off formulas</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">Fixed Purchase Order Cost</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <span className="flex items-center border-r border-divider px-3 text-xs text-ink-secondary">₹</span>
                <input
                  type="number"
                  disabled={!isAdmin}
                  value={formData.orderFixedCost}
                  onChange={(e) => setFormData({ ...formData, orderFixedCost: Number(e.target.value) })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Fixed administrative & delivery overhead per PO</p>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary">L1 Approval Cutoff Deadline</label>
              <div className="mt-1 flex rounded-button border border-border bg-surface">
                <input
                  type="text"
                  disabled={!isAdmin}
                  value={formData.approvalCutoffHourIST}
                  onChange={(e) => setFormData({ ...formData, approvalCutoffHourIST: e.target.value })}
                  className="w-full rounded-button px-3 py-2 text-xs text-ink focus:outline-none disabled:bg-app"
                />
                <span className="flex items-center border-l border-divider px-3 text-xs text-ink-secondary">IST</span>
              </div>
              <p className="mt-1 text-[11px] text-ink-secondary">Daily store supervisor decision cutoff</p>
            </div>
          </div>
        </div>

        {/* Section 3: User Profile & Security Session */}
        <div className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center gap-2 border-b border-divider pb-3">
            <UserCheck className="h-4 w-4 text-brand" />
            <h2 className="text-base font-semibold text-ink">User Profile & Access Scoping</h2>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-button border border-border bg-app p-3">
              <span className="text-[11px] text-ink-secondary">User Full Name</span>
              <div className="font-semibold text-ink">{user?.name}</div>
            </div>

            <div className="rounded-button border border-border bg-app p-3">
              <span className="text-[11px] text-ink-secondary">Assigned Role</span>
              <div className="font-semibold text-brand">
                {isAdmin ? "L2 Super Admin (Chain Authority)" : "L1 Store Supervisor"}
              </div>
            </div>

            <div className="rounded-button border border-border bg-app p-3">
              <span className="text-[11px] text-ink-secondary">Assigned Store Scope</span>
              <div className="font-semibold text-ink">
                {user?.store ? user.store.name : "All Stores (Network Wide)"}
              </div>
            </div>

            <div className="rounded-button border border-border bg-app p-3">
              <span className="text-[11px] text-ink-secondary">Session Status</span>
              <div className="flex items-center gap-1.5 font-semibold text-success">
                <span className="h-2 w-2 rounded-full bg-success" />
                <span>Active JWT Session</span>
              </div>
            </div>
          </div>

          {isAdmin && (
            <div className="mt-5 flex justify-end">
              <button
                type="submit"
                className="flex items-center gap-2 rounded-button bg-brand px-5 py-2 text-xs font-semibold text-white shadow-card transition hover:bg-brand-hover"
              >
                <Save className="h-4 w-4" />
                <span>Save Configuration</span>
              </button>
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
