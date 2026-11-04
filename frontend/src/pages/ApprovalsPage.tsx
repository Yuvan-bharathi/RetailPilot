import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Clock, X } from "lucide-react";

import { useApi } from "../app/ApiContext";
import { useAuth } from "../app/AuthContext";
import { usePurchaseOrders } from "../api/hooks";
import type { PurchaseOrderDTO } from "../api/types";
import { formatINR, formatDateTimeIST } from "../lib/format";

export function ApprovalsPage() {
  const { user } = useAuth();
  const api = useApi();
  const queryClient = useQueryClient();

  const [activePoId, setActivePoId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectModalOpen, setRejectModalOpen] = useState(false);

  const { data: poPage, isLoading } = usePurchaseOrders({
    store_id: user?.role === "STORE_SUPERVISOR" ? user.store?.store_id : undefined,
    status: user?.role === "STORE_SUPERVISOR" ? "PENDING_L1" : undefined,
  });

  const pendingPos = (poPage?.items ?? []).filter((po) => po.status === "PENDING_L1" || po.status === "PENDING_L2");

  const selectedPo = pendingPos.find((p) => p.po_id === activePoId) ?? pendingPos[0] ?? null;

  const decideMutation = useMutation({
    mutationFn: async ({
      poId,
      decision,
      lineEdits,
      reason,
    }: {
      poId: string;
      decision: "APPROVED" | "EDITED" | "REJECTED";
      lineEdits?: { po_line_id: string; qty: number }[];
      reason?: string;
    }) => {
      return api.createApproval({
        entity_type: "PO",
        entity_id: poId,
        store_id: user?.store?.store_id ?? undefined,
        decision,
        line_edits: lineEdits ?? [],
        reason,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setRejectModalOpen(false);
      setRejectReason("");
    },
  });

  const handleApproveAll = (po: PurchaseOrderDTO) => {
    decideMutation.mutate({
      poId: po.po_id,
      decision: "APPROVED",
    });
  };

  const handleRejectClick = (poId: string) => {
    setActivePoId(poId);
    setRejectModalOpen(true);
  };

  const confirmReject = () => {
    if (!selectedPo || !rejectReason.trim()) return;
    decideMutation.mutate({
      poId: selectedPo.po_id,
      decision: "REJECTED",
      reason: rejectReason,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">Approval Centre</h1>
        <p className="text-sm text-ink-secondary">
          {user?.role === "SUPER_ADMIN"
            ? "Review high-value (L2) purchase orders and store escalations."
            : "Review line-level purchase order replenishments for your store."}
        </p>
      </div>

      {isLoading ? (
        <div className="h-64 animate-pulse rounded-card border border-border bg-surface" />
      ) : pendingPos.length === 0 ? (
        <div className="rounded-card border border-border bg-surface p-12 text-center shadow-card">
          <CheckCircle2 className="mx-auto h-12 w-12 text-success" />
          <h3 className="mt-3 text-base font-semibold text-ink">All caught up!</h3>
          <p className="mt-1 text-sm text-ink-secondary">
            No purchase orders or lines currently pending your decision.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left: Pending PO List */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Pending Orders ({pendingPos.length})
            </h2>
            {pendingPos.map((po) => {
              const isSelected = selectedPo?.po_id === po.po_id;
              return (
                <div
                  key={po.po_id}
                  onClick={() => setActivePoId(po.po_id)}
                  className={`cursor-pointer rounded-card border p-4 transition shadow-card ${
                    isSelected
                      ? "border-brand bg-brand-soft/20 ring-1 ring-brand"
                      : "border-border bg-surface hover:border-brand/40"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink">{po.supplier.name}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                        po.status === "PENDING_L2" ? "bg-purple-100 text-purple-800" : "bg-warning-bg text-warning"
                      }`}
                    >
                      {po.status === "PENDING_L2" ? "L2 Super Admin" : "L1 Store Review"}
                    </span>
                  </div>

                  <div className="mt-2 flex items-baseline justify-between">
                    <div className="text-lg font-bold text-ink tabular">{formatINR(po.total_value)}</div>
                    <div className="text-xs text-ink-secondary tabular">{po.lines.length} lines</div>
                  </div>

                  {po.l1_deadline && (
                    <div className="mt-2 flex items-center gap-1.5 text-xs text-warning">
                      <Clock className="h-3.5 w-3.5" />
                      <span>Deadline: {formatDateTimeIST(po.l1_deadline)}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Right: Active Order Line Details */}
          {selectedPo && (
            <div className="rounded-card border border-border bg-surface p-6 shadow-card lg:col-span-2">
              <div className="flex flex-col gap-3 border-b border-divider pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-ink">{selectedPo.supplier.name}</h2>
                    <span className="rounded bg-neutral-bg px-2 py-0.5 text-xs font-medium text-neutral">
                      {selectedPo.required_level}
                    </span>
                  </div>
                  <p className="text-xs text-ink-secondary">
                    Total Value: <span className="font-semibold text-ink">{formatINR(selectedPo.total_value)}</span>
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleRejectClick(selectedPo.po_id)}
                    disabled={decideMutation.isPending}
                    className="flex items-center gap-1.5 rounded-button border border-danger-bg bg-surface px-3 py-1.5 text-xs font-semibold text-danger transition hover:bg-danger-bg/20"
                  >
                    <X className="h-3.5 w-3.5" />
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => handleApproveAll(selectedPo)}
                    disabled={decideMutation.isPending}
                    className="flex items-center gap-1.5 rounded-button bg-brand px-4 py-1.5 text-xs font-semibold text-surface shadow-sm transition hover:bg-brand-hover"
                  >
                    <Check className="h-3.5 w-3.5" />
                    Approve Order
                  </button>
                </div>
              </div>

              {/* Line items table */}
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-divider text-ink-secondary">
                    <tr>
                      <th className="py-2 font-medium">Product / SKU</th>
                      <th className="py-2 font-medium">Store</th>
                      <th className="py-2 font-medium text-right">Unit Price</th>
                      <th className="py-2 font-medium text-right">Order Qty</th>
                      <th className="py-2 font-medium text-right">Line Value</th>
                      <th className="py-2 font-medium text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-divider">
                    {selectedPo.lines.map((line) => {
                      const currentQty = line.qty;
                      return (
                        <tr key={line.po_line_id} className="hover:bg-app/50">
                          <td className="py-3">
                            <div className="font-semibold text-ink">{line.product.name}</div>
                            <div className="text-[11px] text-ink-secondary">{line.product.sku}</div>
                          </td>
                          <td className="py-3 text-ink-secondary">{line.store.name}</td>
                          <td className="py-3 text-right font-medium text-ink tabular">{formatINR(line.unit_price)}</td>
                          <td className="py-3 text-right tabular">
                            <span className="font-semibold text-ink">{currentQty}</span>
                          </td>
                          <td className="py-3 text-right font-semibold text-ink tabular">
                            {formatINR(line.line_value)}
                          </td>
                          <td className="py-3 text-center">
                            <span
                              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                line.line_status === "APPROVED"
                                  ? "bg-success-bg text-success"
                                  : line.line_status === "REJECTED"
                                    ? "bg-danger-bg text-danger"
                                    : "bg-warning-bg text-warning"
                              }`}
                            >
                              {line.line_status}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Reject Modal */}
      {rejectModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-modal bg-surface p-6 shadow-dropdown">
            <h3 className="text-base font-bold text-ink">Reject Purchase Order Decision</h3>
            <p className="mt-1 text-xs text-ink-secondary">
              A written reason is required to notify suppliers and adjust future demand models.
            </p>

            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Provide reason for rejection (e.g., budget reallocation, supplier quote discrepancy)..."
              rows={4}
              className="mt-3 w-full rounded-input border border-border bg-app p-2.5 text-xs text-ink focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="rounded-button border border-border px-3 py-1.5 text-xs font-semibold text-ink hover:bg-app"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmReject}
                disabled={!rejectReason.trim() || decideMutation.isPending}
                className="rounded-button bg-danger px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-danger/90 disabled:opacity-50"
              >
                Confirm Rejection
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
