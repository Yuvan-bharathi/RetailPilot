import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, ArrowRight, CheckCircle2, Send } from "lucide-react";

import { useApi } from "../app/ApiContext";
import { useAuth } from "../app/AuthContext";
import { useTransfers } from "../api/hooks";
import type { TransferOrderDTO, TransferStatus } from "../api/types";
import { formatINR } from "../lib/format";

type TabMode = "ALL" | "INBOUND" | "OUTBOUND";

export function TransfersPage() {
  const { user } = useAuth();
  const api = useApi();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<TabMode>("ALL");
  const [selectedTransfer, setSelectedTransfer] = useState<TransferOrderDTO | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [receivedQty, setReceivedQty] = useState<number>(0);
  const [showRejectModal, setShowRejectModal] = useState(false);

  const myStoreId = user?.store?.store_id;

  const { data: page, isLoading } = useTransfers({
    store_id: user?.role === "STORE_SUPERVISOR" ? myStoreId : undefined,
  });

  const transfers = page?.items ?? [];

  const filteredTransfers = transfers.filter((t) => {
    if (tab === "INBOUND") return t.to_store.store_id === myStoreId;
    if (tab === "OUTBOUND") return t.from_store.store_id === myStoreId;
    return true;
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["transfers"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    queryClient.invalidateQueries({ queryKey: ["inv"] });
    setSelectedTransfer(null);
  };

  const acceptMutation = useMutation({
    mutationFn: (id: string) => api.acceptTransfer(id),
    onSuccess: invalidate,
  });

  const approveReleaseMutation = useMutation({
    mutationFn: (id: string) => api.approveReleaseTransfer(id),
    onSuccess: invalidate,
  });

  const dispatchMutation = useMutation({
    mutationFn: (id: string) => api.dispatchTransfer(id),
    onSuccess: invalidate,
  });

  const receiveMutation = useMutation({
    mutationFn: ({ id, qty }: { id: string; qty: number }) => api.receiveTransfer(id, qty),
    onSuccess: invalidate,
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.rejectTransfer(id, reason),
    onSuccess: () => {
      setShowRejectModal(false);
      setRejectReason("");
      invalidate();
    },
  });

  const statusBadge = (status: TransferStatus) => {
    switch (status) {
      case "PROPOSED":
        return <span className="rounded-full bg-info-bg px-2.5 py-0.5 text-xs font-semibold text-info">Proposed</span>;
      case "DEST_ACCEPTED":
        return (
          <span className="rounded-full bg-warning-bg px-2.5 py-0.5 text-xs font-semibold text-warning">
            Dest Accepted
          </span>
        );
      case "DONOR_APPROVED":
        return (
          <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-800">
            Donor Approved
          </span>
        );
      case "DISPATCHED":
        return (
          <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-800">In Transit</span>
        );
      case "RECEIVED":
        return (
          <span className="rounded-full bg-success-bg px-2.5 py-0.5 text-xs font-semibold text-success">Received</span>
        );
      case "REJECTED":
        return (
          <span className="rounded-full bg-danger-bg px-2.5 py-0.5 text-xs font-semibold text-danger">Rejected</span>
        );
      default:
        return (
          <span className="rounded-full bg-neutral-bg px-2.5 py-0.5 text-xs font-semibold text-neutral">{status}</span>
        );
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Stock Balancing Transfers</h1>
          <p className="text-sm text-ink-secondary">
            Cross-store inventory rebalancing engine with donor requirement protection.
          </p>
        </div>

        {/* Tab Filters */}
        <div className="flex rounded-button border border-border bg-surface p-1 shadow-sm">
          <button
            type="button"
            onClick={() => setTab("ALL")}
            className={`rounded px-3 py-1.5 text-xs font-medium transition ${
              tab === "ALL" ? "bg-brand text-white" : "text-ink-secondary hover:text-ink"
            }`}
          >
            All Transfers ({transfers.length})
          </button>
          {user?.role === "STORE_SUPERVISOR" && (
            <>
              <button
                type="button"
                onClick={() => setTab("INBOUND")}
                className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                  tab === "INBOUND" ? "bg-brand text-white" : "text-ink-secondary hover:text-ink"
                }`}
              >
                Inbound to Receive
              </button>
              <button
                type="button"
                onClick={() => setTab("OUTBOUND")}
                className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                  tab === "OUTBOUND" ? "bg-brand text-white" : "text-ink-secondary hover:text-ink"
                }`}
              >
                Outbound to Dispatch
              </button>
            </>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="h-64 animate-pulse rounded-card border border-border bg-surface" />
      ) : filteredTransfers.length === 0 ? (
        <div className="rounded-card border border-border bg-surface p-12 text-center shadow-card">
          <ArrowLeftRight className="mx-auto h-12 w-12 text-ink-secondary/60" />
          <h3 className="mt-3 text-base font-semibold text-ink">No transfers found</h3>
          <p className="mt-1 text-sm text-ink-secondary">No stock transfers match the current filter selection.</p>
        </div>
      ) : (
        <div className="rounded-card border border-border bg-surface shadow-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-divider bg-app/50 text-ink-secondary">
                <tr>
                  <th className="py-3 px-4 font-medium">Product / SKU</th>
                  <th className="py-3 px-4 font-medium">Transfer Route</th>
                  <th className="py-3 px-4 font-medium text-right">Transfer Qty</th>
                  <th className="py-3 px-4 font-medium text-right">Est. Cost</th>
                  <th className="py-3 px-4 font-medium text-center">Transit</th>
                  <th className="py-3 px-4 font-medium text-center">Status</th>
                  <th className="py-3 px-4 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-divider">
                {filteredTransfers.map((t) => {
                  const isReceiver = t.to_store.store_id === myStoreId;
                  const isDonor = t.from_store.store_id === myStoreId;
                  const isSuper = user?.role === "SUPER_ADMIN";

                  return (
                    <tr key={t.transfer_id} className="hover:bg-app/40 transition">
                      <td className="py-3.5 px-4">
                        <div className="font-semibold text-ink">{t.product.name}</div>
                        <div className="text-[11px] text-ink-secondary">
                          {t.product.sku} • {t.product.category}
                        </div>
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1.5 font-medium text-ink">
                          <span>{t.from_store.name}</span>
                          <ArrowRight className="h-3 w-3 text-brand" />
                          <span>{t.to_store.name}</span>
                        </div>
                        {t.is_expiry_aware && (
                          <span className="text-[10px] font-semibold text-warning">Expiry-Aware Transfer</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-right font-bold text-ink tabular">{t.qty} units</td>
                      <td className="py-3.5 px-4 text-right font-medium text-ink tabular">
                        {t.transfer_cost ? formatINR(t.transfer_cost) : "—"}
                      </td>
                      <td className="py-3.5 px-4 text-center tabular text-ink-secondary">{t.transit_days}d</td>
                      <td className="py-3.5 px-4 text-center">{statusBadge(t.status)}</td>
                      <td className="py-3.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {/* Step 1: Destination accepts */}
                          {t.status === "PROPOSED" && (isReceiver || isSuper) && (
                            <button
                              type="button"
                              onClick={() => acceptMutation.mutate(t.transfer_id)}
                              disabled={acceptMutation.isPending}
                              className="rounded-button bg-brand px-2.5 py-1 text-xs font-semibold text-white hover:bg-brand-hover shadow-xs"
                            >
                              Accept
                            </button>
                          )}

                          {/* Step 2: Donor approves release */}
                          {t.status === "DEST_ACCEPTED" && (isDonor || isSuper) && (
                            <button
                              type="button"
                              onClick={() => approveReleaseMutation.mutate(t.transfer_id)}
                              disabled={approveReleaseMutation.isPending}
                              className="rounded-button bg-brand px-2.5 py-1 text-xs font-semibold text-white hover:bg-brand-hover shadow-xs"
                            >
                              Approve Release
                            </button>
                          )}

                          {/* Step 3: Donor dispatches */}
                          {t.status === "DONOR_APPROVED" && (isDonor || isSuper) && (
                            <button
                              type="button"
                              onClick={() => dispatchMutation.mutate(t.transfer_id)}
                              disabled={dispatchMutation.isPending}
                              className="flex items-center gap-1 rounded-button bg-brand px-2.5 py-1 text-xs font-semibold text-white hover:bg-brand-hover shadow-xs"
                            >
                              <Send className="h-3 w-3" />
                              Dispatch
                            </button>
                          )}

                          {/* Step 4: Destination receives */}
                          {t.status === "DISPATCHED" && (isReceiver || isSuper) && (
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedTransfer(t);
                                setReceivedQty(t.qty);
                              }}
                              className="flex items-center gap-1 rounded-button bg-success px-2.5 py-1 text-xs font-semibold text-white hover:bg-success/90 shadow-xs"
                            >
                              <CheckCircle2 className="h-3 w-3" />
                              Receive
                            </button>
                          )}

                          {/* Reject Option */}
                          {(t.status === "PROPOSED" || t.status === "DEST_ACCEPTED") &&
                            (isReceiver || isDonor || isSuper) && (
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedTransfer(t);
                                  setShowRejectModal(true);
                                }}
                                className="rounded-button border border-border px-2 py-1 text-xs font-semibold text-ink-secondary hover:text-danger hover:border-danger-bg"
                              >
                                Reject
                              </button>
                            )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Receive Stock Modal */}
      {selectedTransfer && !showRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-sm rounded-modal bg-surface p-6 shadow-dropdown">
            <h3 className="text-base font-bold text-ink">Confirm Transfer Receipt</h3>
            <p className="mt-1 text-xs text-ink-secondary">
              Incoming from {selectedTransfer.from_store.name}: {selectedTransfer.product.name}
            </p>

            <div className="mt-4">
              <label className="text-xs font-semibold text-ink">Received Quantity (units)</label>
              <input
                type="number"
                min={0}
                value={receivedQty}
                onChange={(e) => setReceivedQty(Number(e.target.value))}
                className="mt-1.5 w-full rounded-input border border-border bg-app p-2 text-xs font-semibold text-ink"
              />
              <p className="mt-1 text-[11px] text-ink-secondary">Dispatched: {selectedTransfer.qty} units</p>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSelectedTransfer(null)}
                className="rounded-button border border-border px-3 py-1.5 text-xs font-semibold text-ink hover:bg-app"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => receiveMutation.mutate({ id: selectedTransfer.transfer_id, qty: receivedQty })}
                disabled={receiveMutation.isPending}
                className="rounded-button bg-brand px-4 py-1.5 text-xs font-semibold text-white hover:bg-brand-hover shadow-xs"
              >
                Confirm Receipt
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reject Modal */}
      {showRejectModal && selectedTransfer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-sm rounded-modal bg-surface p-6 shadow-dropdown">
            <h3 className="text-base font-bold text-ink">Decline Transfer Request</h3>
            <p className="mt-1 text-xs text-ink-secondary">
              A written reason is required so the replenishment engine can re-evaluate.
            </p>

            <textarea
              rows={3}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Reason for declining transfer..."
              className="mt-3 w-full rounded-input border border-border bg-app p-2 text-xs text-ink focus:border-brand focus:outline-none"
            />

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowRejectModal(false);
                  setSelectedTransfer(null);
                }}
                className="rounded-button border border-border px-3 py-1.5 text-xs font-semibold text-ink hover:bg-app"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => rejectMutation.mutate({ id: selectedTransfer.transfer_id, reason: rejectReason })}
                disabled={!rejectReason.trim() || rejectMutation.isPending}
                className="rounded-button bg-danger px-4 py-1.5 text-xs font-semibold text-white hover:bg-danger/90 disabled:opacity-50"
              >
                Decline Transfer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
