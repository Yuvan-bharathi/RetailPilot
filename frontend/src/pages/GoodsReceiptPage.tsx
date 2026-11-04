import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Truck } from "lucide-react";

import { useApi } from "../app/ApiContext";
import { useAuth } from "../app/AuthContext";
import { usePurchaseOrders } from "../api/hooks";
import type { POLineDTO } from "../api/types";
import { formatINR } from "../lib/format";

export function GoodsReceiptPage() {
  const { user } = useAuth();
  const api = useApi();
  const queryClient = useQueryClient();

  const [selectedPoId, setSelectedPoId] = useState<string | null>(null);
  const [receivedQtys, setReceivedQtys] = useState<Record<string, number>>({});
  const [batchNos, setBatchNos] = useState<Record<string, string>>({});
  const [expiryDates, setExpiryDates] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const { data: page, isLoading } = usePurchaseOrders({
    store_id: user?.store?.store_id ?? undefined,
    status: "SUBMITTED",
  });

  const orders = page?.items ?? [];
  const activePo = orders.find((p) => p.po_id === selectedPoId) ?? orders[0] ?? null;

  const receiveMutation = useMutation({
    mutationFn: async ({ poId, lines }: { poId: string; lines: POLineDTO[] }) => {
      const receiptLines = lines
        .filter((l) => (receivedQtys[l.po_line_id] ?? 0) > 0)
        .map((l) => ({
          po_line_id: l.po_line_id,
          qty: Number(receivedQtys[l.po_line_id] ?? 0),
          batch_no: batchNos[l.po_line_id] || undefined,
          expiry_date: expiryDates[l.po_line_id] || undefined,
        }));

      if (receiptLines.length === 0) {
        throw new Error("Enter received quantity for at least one line item");
      }

      return api.receiveGoods(poId, { lines: receiptLines, note: note || undefined });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      queryClient.invalidateQueries({ queryKey: ["inv"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setSuccessMessage("Goods receipt successfully posted to stock ledger and batch inventory.");
      setTimeout(() => setSuccessMessage(null), 5000);
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">Goods Delivery Receipt</h1>
        <p className="text-sm text-ink-secondary">
          Receive deliveries from suppliers, verify quantities, assign batch tags, and post directly to the stock
          ledger.
        </p>
      </div>

      {successMessage && (
        <div className="flex items-center gap-2 rounded-card border border-success bg-success-bg p-4 text-xs font-semibold text-success shadow-xs">
          <CheckCircle2 className="h-4 w-4" />
          <span>{successMessage}</span>
        </div>
      )}

      {isLoading ? (
        <div className="h-64 animate-pulse rounded-card border border-border bg-surface" />
      ) : orders.length === 0 ? (
        <div className="rounded-card border border-border bg-surface p-12 text-center shadow-card">
          <Truck className="mx-auto h-12 w-12 text-ink-secondary/60" />
          <h3 className="mt-3 text-base font-semibold text-ink">No deliveries pending</h3>
          <p className="mt-1 text-sm text-ink-secondary">
            There are no submitted purchase orders awaiting goods delivery.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Orders selection */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Awaiting Delivery ({orders.length})
            </h2>
            {orders.map((po) => {
              const isSelected = activePo?.po_id === po.po_id;
              return (
                <div
                  key={po.po_id}
                  onClick={() => setSelectedPoId(po.po_id)}
                  className={`cursor-pointer rounded-card border p-4 transition shadow-card ${
                    isSelected
                      ? "border-brand bg-brand-soft/20 ring-1 ring-brand"
                      : "border-border bg-surface hover:border-brand/40"
                  }`}
                >
                  <div className="flex items-center justify-between font-semibold text-ink">
                    <span>{po.supplier.name}</span>
                    <span className="text-xs text-brand tabular font-bold">{formatINR(po.total_value)}</span>
                  </div>
                  <div className="mt-1 text-xs text-ink-secondary">{po.lines.length} items ordered for your store</div>
                </div>
              );
            })}
          </div>

          {/* Receiving Form */}
          {activePo && (
            <div className="rounded-card border border-border bg-surface p-6 shadow-card lg:col-span-2 space-y-5">
              <div className="flex items-center justify-between border-b border-divider pb-4">
                <div>
                  <h2 className="text-base font-bold text-ink">Delivery Intake: {activePo.supplier.name}</h2>
                  <p className="text-xs text-ink-secondary">Record received quantities and batch information.</p>
                </div>
                <button
                  type="button"
                  onClick={() => receiveMutation.mutate({ poId: activePo.po_id, lines: activePo.lines })}
                  disabled={receiveMutation.isPending}
                  className="flex items-center gap-1.5 rounded-button bg-brand px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-brand-hover disabled:opacity-50"
                >
                  <Check className="h-4 w-4" />
                  Post to Ledger
                </button>
              </div>

              <div className="space-y-4">
                {activePo.lines.map((ln) => {
                  const remQty = Math.max(0, ln.qty - ln.received_qty);
                  return (
                    <div key={ln.po_line_id} className="rounded-card border border-border bg-app/30 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-semibold text-ink text-sm">{ln.product.name}</div>
                          <div className="text-xs text-ink-secondary">
                            SKU: {ln.product.sku} • Ordered: <span className="font-bold text-ink">{ln.qty}</span> •
                            Already received: {ln.received_qty}
                          </div>
                        </div>
                        <span className="text-xs font-semibold text-brand tabular">Remaining: {remQty} units</span>
                      </div>

                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <div>
                          <label className="text-[11px] font-medium text-ink-secondary">Received Qty (units)</label>
                          <input
                            type="number"
                            min={0}
                            max={remQty}
                            value={receivedQtys[ln.po_line_id] ?? remQty}
                            onChange={(e) =>
                              setReceivedQtys((prev) => ({
                                ...prev,
                                [ln.po_line_id]: Number(e.target.value),
                              }))
                            }
                            className="mt-1 w-full rounded-input border border-border bg-surface p-2 text-xs font-semibold text-ink"
                          />
                        </div>

                        <div>
                          <label className="text-[11px] font-medium text-ink-secondary">Batch / Lot Number</label>
                          <input
                            type="text"
                            placeholder="e.g. BATCH-2026-X"
                            value={batchNos[ln.po_line_id] ?? ""}
                            onChange={(e) =>
                              setBatchNos((prev) => ({
                                ...prev,
                                [ln.po_line_id]: e.target.value,
                              }))
                            }
                            className="mt-1 w-full rounded-input border border-border bg-surface p-2 text-xs text-ink"
                          />
                        </div>

                        <div>
                          <label className="text-[11px] font-medium text-ink-secondary">Expiry Date</label>
                          <input
                            type="date"
                            value={expiryDates[ln.po_line_id] ?? ""}
                            onChange={(e) =>
                              setExpiryDates((prev) => ({
                                ...prev,
                                [ln.po_line_id]: e.target.value,
                              }))
                            }
                            className="mt-1 w-full rounded-input border border-border bg-surface p-2 text-xs text-ink"
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div>
                <label className="text-xs font-medium text-ink-secondary">Intake Note / Delivery Challan</label>
                <input
                  type="text"
                  placeholder="Optional delivery memo or invoice number..."
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  className="mt-1.5 w-full rounded-input border border-border bg-surface p-2 text-xs text-ink"
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
