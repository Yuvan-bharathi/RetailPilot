import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  Bot,
  Calendar,
  CheckCircle2,
  Clock,
  Cpu,
  Play,
  RotateCw,
  Search,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { useState } from "react";

import { useApi } from "../app/ApiContext";
import { useAuth } from "../app/AuthContext";
import { useAgentRun, useAgentRuns } from "../api/hooks";
import type { AgentRunDetailDTO } from "../api/types";
import { formatDateTimeIST } from "../lib/format";

export function MonitoringPage() {
  const { user } = useAuth();
  const api = useApi();
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [agentFilter, setAgentFilter] = useState<string>("ALL");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const runsQuery = useAgentRuns(100);
  const detailQuery = useAgentRun(selectedRunId);

  const triggerMutation = useMutation({
    mutationFn: () => api.triggerNightlyRun(),
    onSuccess: (data) => {
      setTriggerMsg(`Nightly run queued successfully (Date: ${data.run_date})`);
      void queryClient.invalidateQueries({ queryKey: ["agent-runs"] });
    },
    onError: (err: Error) => {
      setTriggerMsg(`Failed to trigger: ${err.message}`);
    },
  });

  const runs = runsQuery.data ?? [];

  const filteredRuns = runs.filter((r) => {
    const matchesAgent = agentFilter === "ALL" || r.agent_name === agentFilter;
    const matchesStatus = statusFilter === "ALL" || r.status === statusFilter;
    const matchesSearch =
      searchTerm === "" ||
      r.agent_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (r.output_summary && r.output_summary.toLowerCase().includes(searchTerm.toLowerCase())) ||
      r.run_id.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesAgent && matchesStatus && matchesSearch;
  });

  // Calculate summary metrics
  const totalRuns = runs.length;
  const successRuns = runs.filter((r) => r.status === "SUCCESS").length;
  const partialRuns = runs.filter((r) => r.status === "PARTIAL").length;
  const failedRuns = runs.filter((r) => r.status === "FAILED").length;
  const totalToolCalls = runs.reduce((sum, r) => sum + (r.tool_calls?.length ?? 0), 0);
  const totalTokens = runs.reduce(
    (sum, r) => sum + (r.llm_usages?.reduce((usum, u) => usum + u.input_tokens + u.output_tokens, 0) ?? 0),
    0,
  );

  const uniqueAgentNames = Array.from(new Set(runs.map((r) => r.agent_name))).sort();

  return (
    <div className="space-y-6">
      {/* Top Header & Trigger Action */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold tracking-tight text-ink">Agent Observability & System Monitoring</h2>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-success-bg px-2.5 py-0.5 text-xs font-medium text-success">
              <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
              Live Telemetry
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-secondary">
            Inspect autonomous replenishment agents, tool invocations, LLM token metrics, and execution traces.
          </p>
        </div>

        {user?.role === "SUPER_ADMIN" && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={triggerMutation.isPending}
              onClick={() => triggerMutation.mutate()}
              className="inline-flex items-center gap-2 rounded-button bg-brand px-4 py-2 text-sm font-semibold text-surface shadow-card hover:bg-brand-hover disabled:opacity-50"
            >
              {triggerMutation.isPending ? (
                <>
                  <RotateCw className="h-4 w-4 animate-spin" />
                  Queueing…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Trigger Nightly Pipeline
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {triggerMsg && (
        <div className="flex items-center justify-between rounded-card border border-border bg-surface p-4 text-sm text-ink shadow-card">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-brand" />
            <span>{triggerMsg}</span>
          </div>
          <button
            type="button"
            onClick={() => setTriggerMsg(null)}
            className="rounded p-1 text-ink-secondary hover:bg-elevated hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* KPI Metric Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="text-xs font-medium uppercase tracking-wider text-ink-secondary">Total Runs</div>
          <div className="mt-2 text-2xl font-bold text-ink tabular">{totalRuns}</div>
          <div className="mt-1 text-xs text-ink-secondary">Recorded pipeline cycles</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="text-xs font-medium uppercase tracking-wider text-ink-secondary">Successful</div>
          <div className="mt-2 text-2xl font-bold text-success tabular">{successRuns}</div>
          <div className="mt-1 text-xs text-ink-secondary">100% completion</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="text-xs font-medium uppercase tracking-wider text-ink-secondary">Partial Runs</div>
          <div className="mt-2 text-2xl font-bold text-warning tabular">{partialRuns}</div>
          <div className="mt-1 text-xs text-ink-secondary">Non-critical retries</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="text-xs font-medium uppercase tracking-wider text-ink-secondary">Failed Runs</div>
          <div className="mt-2 text-2xl font-bold text-danger tabular">{failedRuns}</div>
          <div className="mt-1 text-xs text-ink-secondary">Critical aborts</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="text-xs font-medium uppercase tracking-wider text-ink-secondary">Tool Calls</div>
          <div className="mt-2 text-2xl font-bold text-accent-blue tabular">{totalToolCalls}</div>
          <div className="mt-1 text-xs text-ink-secondary">Executed tools</div>
        </div>

        <div className="rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="text-xs font-medium uppercase tracking-wider text-ink-secondary">LLM Tokens</div>
          <div className="mt-2 text-2xl font-bold text-accent-lavender tabular">{totalTokens.toLocaleString()}</div>
          <div className="mt-1 text-xs text-ink-secondary">Inference volume</div>
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
            placeholder="Search runs by agent name, summary, ID…"
            className="w-full bg-transparent text-sm text-ink placeholder:text-ink-disabled focus:outline-none"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="h-8 rounded-input border border-border bg-surface px-2.5 text-xs text-ink focus:outline-none"
          >
            <option value="ALL">All Agents</option>
            {uniqueAgentNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-8 rounded-input border border-border bg-surface px-2.5 text-xs text-ink focus:outline-none"
          >
            <option value="ALL">All Statuses</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="PARTIAL">PARTIAL</option>
            <option value="FAILED">FAILED</option>
            <option value="RUNNING">RUNNING</option>
          </select>

          <button
            type="button"
            onClick={() => void runsQuery.refetch()}
            className="inline-flex h-8 items-center gap-1 rounded-button border border-border bg-elevated px-2.5 text-xs font-medium text-ink hover:bg-surface"
          >
            <RotateCw className={`h-3 w-3 ${runsQuery.isFetching ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Main Runs Table */}
      <div className="rounded-card border border-border bg-surface shadow-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-app/50 text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              <tr>
                <th className="py-3 px-4">Agent Name</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Run Date</th>
                <th className="py-3 px-4">Started At</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4">Summary</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border text-ink">
              {runsQuery.isLoading ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-ink-secondary">
                    Loading agent executions…
                  </td>
                </tr>
              ) : filteredRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-ink-secondary">
                    No agent runs match the selected criteria.
                  </td>
                </tr>
              ) : (
                filteredRuns.map((r) => {
                  const started = new Date(r.started_at).getTime();
                  const finished = r.finished_at ? new Date(r.finished_at).getTime() : null;
                  const durationSec = finished ? ((finished - started) / 1000).toFixed(1) : null;

                  return (
                    <tr
                      key={r.run_id}
                      onClick={() => setSelectedRunId(r.run_id)}
                      className={`cursor-pointer transition-colors hover:bg-elevated/70 ${
                        selectedRunId === r.run_id ? "bg-brand-soft/40" : ""
                      }`}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <Bot className="h-4 w-4 text-brand shrink-0" />
                          <span className="font-semibold text-ink">{r.agent_name}</span>
                        </div>
                      </td>

                      <td className="py-3 px-4">
                        <StatusPill status={r.status} />
                      </td>

                      <td className="py-3 px-4 text-ink-secondary tabular">{r.run_date ?? "—"}</td>

                      <td className="py-3 px-4 text-ink-secondary tabular text-xs">
                        {formatDateTimeIST(r.started_at)}
                      </td>

                      <td className="py-3 px-4 text-ink-secondary tabular text-xs">
                        {durationSec ? `${durationSec}s` : "In progress"}
                      </td>

                      <td
                        className="py-3 px-4 max-w-xs truncate text-xs text-ink-secondary"
                        title={r.output_summary ?? ""}
                      >
                        {r.output_summary || r.error || "—"}
                      </td>

                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedRunId(r.run_id);
                          }}
                          className="rounded-button px-2.5 py-1 text-xs font-semibold text-brand hover:bg-brand-soft"
                        >
                          View Trace →
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Run Trace Drawer / Detail Modal */}
      {selectedRunId && (
        <RunDetailDrawer
          runId={selectedRunId}
          detail={detailQuery.data ?? null}
          isLoading={detailQuery.isLoading}
          onClose={() => setSelectedRunId(null)}
        />
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  if (status === "SUCCESS") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-success-bg px-2.5 py-0.5 text-xs font-medium text-success">
        <CheckCircle2 className="h-3 w-3" />
        SUCCESS
      </span>
    );
  }
  if (status === "PARTIAL") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-warning-bg px-2.5 py-0.5 text-xs font-medium text-warning">
        <AlertCircle className="h-3 w-3" />
        PARTIAL
      </span>
    );
  }
  if (status === "FAILED") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-danger-bg px-2.5 py-0.5 text-xs font-medium text-danger">
        <AlertCircle className="h-3 w-3" />
        FAILED
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-neutral-bg px-2.5 py-0.5 text-xs font-medium text-neutral">
      <RotateCw className="h-3 w-3 animate-spin" />
      {status}
    </span>
  );
}

function RunDetailDrawer({
  runId,
  detail,
  isLoading,
  onClose,
}: {
  runId: string;
  detail: AgentRunDetailDTO | null;
  isLoading: boolean;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-modal border border-border bg-surface shadow-dropdown overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-card bg-brand-soft text-brand">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-bold text-ink">{detail?.agent_name ?? "Agent Run Trace"}</h3>
                {detail && <StatusPill status={detail.status} />}
              </div>
              <p className="text-xs text-ink-secondary tabular font-mono">Run ID: {runId}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-button p-2 text-ink-secondary hover:bg-elevated hover:text-ink"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {isLoading ? (
            <div className="py-12 text-center text-ink-secondary">Loading detailed telemetry and traces…</div>
          ) : !detail ? (
            <div className="py-12 text-center text-ink-secondary">Trace details not found for this execution.</div>
          ) : (
            <>
              {/* Timing & Summary */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="rounded-card border border-border bg-elevated p-3">
                  <div className="flex items-center gap-1.5 text-xs text-ink-secondary">
                    <Clock className="h-3.5 w-3.5" />
                    Started At
                  </div>
                  <div className="mt-1 text-sm font-semibold text-ink tabular">
                    {formatDateTimeIST(detail.started_at)}
                  </div>
                </div>

                <div className="rounded-card border border-border bg-elevated p-3">
                  <div className="flex items-center gap-1.5 text-xs text-ink-secondary">
                    <Calendar className="h-3.5 w-3.5" />
                    Run Target Date
                  </div>
                  <div className="mt-1 text-sm font-semibold text-ink tabular">{detail.run_date ?? "N/A"}</div>
                </div>

                <div className="rounded-card border border-border bg-elevated p-3">
                  <div className="flex items-center gap-1.5 text-xs text-ink-secondary">
                    <Cpu className="h-3.5 w-3.5" />
                    Parent Run
                  </div>
                  <div className="mt-1 text-xs font-mono text-ink-secondary truncate">
                    {detail.parent_run_id ?? "Root orchestrator"}
                  </div>
                </div>
              </div>

              {/* Output Summary / Error */}
              {detail.error ? (
                <div className="rounded-card border border-danger/30 bg-danger-bg p-4 text-sm text-danger">
                  <div className="font-semibold flex items-center gap-1.5">
                    <AlertCircle className="h-4 w-4" />
                    Execution Error
                  </div>
                  <pre className="mt-2 text-xs font-mono whitespace-pre-wrap">{detail.error}</pre>
                </div>
              ) : (
                <div className="rounded-card border border-border bg-surface p-4">
                  <div className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
                    Output Summary
                  </div>
                  <p className="mt-2 text-sm text-ink leading-relaxed">
                    {detail.output_summary || "No textual output summary provided."}
                  </p>
                </div>
              )}

              {/* Tool Calls Section */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="flex items-center gap-1.5 text-sm font-bold text-ink">
                    <Wrench className="h-4 w-4 text-accent-blue" />
                    Tool Invocations ({detail.tool_calls?.length ?? 0})
                  </h4>
                </div>

                {!detail.tool_calls || detail.tool_calls.length === 0 ? (
                  <p className="text-xs text-ink-secondary italic">No tools called during this run.</p>
                ) : (
                  <div className="divide-y divide-border rounded-card border border-border bg-surface overflow-hidden">
                    {detail.tool_calls.map((tc) => (
                      <div key={tc.tool_call_id} className="p-3 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-semibold text-ink">{tc.tool_name}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-ink-secondary tabular">{tc.duration_ms} ms</span>
                            <span
                              className={`rounded px-1.5 py-0.5 font-medium ${
                                tc.status === "SUCCESS" ? "bg-success-bg text-success" : "bg-danger-bg text-danger"
                              }`}
                            >
                              {tc.status}
                            </span>
                          </div>
                        </div>
                        {tc.args && Object.keys(tc.args).length > 0 && (
                          <pre className="mt-1.5 max-h-32 overflow-y-auto rounded bg-app p-2 font-mono text-ink-secondary">
                            {JSON.stringify(tc.args, null, 2)}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* LLM Inference Usage Section */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="flex items-center gap-1.5 text-sm font-bold text-ink">
                    <Sparkles className="h-4 w-4 text-brand" />
                    LLM Token Usage ({detail.llm_usages?.length ?? 0} calls)
                  </h4>
                </div>

                {!detail.llm_usages || detail.llm_usages.length === 0 ? (
                  <p className="text-xs text-ink-secondary italic">Deterministic logic; no LLM tokens consumed.</p>
                ) : (
                  <div className="divide-y divide-border rounded-card border border-border bg-surface overflow-hidden">
                    {detail.llm_usages.map((u) => (
                      <div key={u.usage_id} className="p-3 text-xs flex items-center justify-between">
                        <div>
                          <div className="font-semibold text-ink">
                            {u.provider} · <span className="font-mono text-ink-secondary">{u.model}</span>
                          </div>
                          <div className="mt-0.5 text-ink-secondary">
                            Prompt: <span className="tabular font-medium text-ink">{u.input_tokens}</span> · Completion:{" "}
                            <span className="tabular font-medium text-ink">{u.output_tokens}</span>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="font-bold text-brand tabular">
                            {(u.input_tokens + u.output_tokens).toLocaleString()} tokens
                          </div>
                          <div className="text-ink-secondary tabular text-[11px]">
                            {formatDateTimeIST(u.created_at)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Modal Footer */}
        <div className="border-t border-border bg-app/50 px-6 py-3 text-right">
          <button
            type="button"
            onClick={onClose}
            className="rounded-button bg-surface border border-border px-4 py-2 text-sm font-semibold text-ink hover:bg-elevated"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
