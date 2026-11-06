/** Agents → Logs (docs/09 §3.5): agent runs (cursor paging, filters) and the run trace page. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Download, OctagonAlert, Square, Sparkles, StopCircle, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useApi } from "../../app/ApiContext";
import { useAgentRun, useAgentRuns, useAgents } from "../../api/hooks";
import type { AgentRunItemDTO, RunStatus, TraceStepDTO, TriggerType } from "../../api/types";
import { Button } from "../../components/Button";
import { DataTable, type Column } from "../../components/DataTable";
import { ConfirmDialog } from "../../components/Modal";
import { ErrorState, SkeletonLine } from "../../components/StateViews";
import { StatusBadge } from "../../components/StatusBadge";
import {
  DemoBadge,
  AgentLink,
  ConsoleTabs,
  Panel,
  RunStatusBadge,
  Select,
  When,
} from "../../components/agents/agentUi";
import { formatMs, formatUsd, RUN_STATUS, RUN_STATUSES, TRIGGER_LABEL, TRIGGER_TYPES } from "../../lib/agentFormat";
import { formatNumber } from "../../lib/format";
import { useCursorPaging } from "../../lib/useCursorPaging";

export function AgentLogsPage() {
  const navigate = useNavigate();
  const paging = useCursorPaging(25);
  const agents = useAgents();
  const [agentKey, setAgentKey] = useState("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [trigger, setTrigger] = useState<TriggerType | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const result = useAgentRuns({
    cursor: paging.cursor,
    page_size: paging.query.pageSize,
    agent_key: agentKey || undefined,
    status: status || undefined,
    trigger_type: trigger || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });
  const reset =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      paging.reset();
    };

  const columns: Column<AgentRunItemDTO>[] = [
    { id: "started_at", header: "Started", cell: (r) => <When at={r.started_at} /> },
    {
      id: "agent",
      header: "Agent",
      cell: (r) =>
        r.parent_run_id === null && !r.agent_key ? (
          <span className="font-medium">Nightly pipeline</span>
        ) : (
          <AgentLink agentKey={r.agent_key} name={r.agent_name} />
        ),
    },
    { id: "status", header: "Status", cell: (r) => <RunStatusBadge status={r.status} /> },
    {
      id: "trigger",
      header: "Trigger",
      cell: (r) => (
        <span>
          {TRIGGER_LABEL[r.trigger_type]} <DemoBadge show={r.is_demo} />
          {r.triggered_by ? <span className="block text-xs text-ink-secondary">by {r.triggered_by}</span> : null}
        </span>
      ),
    },
    { id: "duration", header: "Duration", cell: (r) => formatMs(r.duration_ms), align: "right" },
    { id: "tools", header: "Tool calls", cell: (r) => r.tool_calls, align: "right" },
    { id: "llm", header: "LLM calls", cell: (r) => r.llm_calls, align: "right" },
    { id: "tokens", header: "Tokens", cell: (r) => formatNumber(r.tokens), align: "right" },
    { id: "cost", header: "Est. cost", cell: (r) => formatUsd(r.est_cost_usd), align: "right" },
    { id: "retries", header: "Retries", cell: (r) => r.retries, align: "right" },
    {
      id: "stop",
      header: "Stop reason / error",
      cell: (r) => (r.error ? <span className="text-danger">{r.error}</span> : (r.stop_reason ?? "—")),
    },
  ];

  return (
    <div className="space-y-5">
      <ConsoleTabs />
      <DataTable
        caption="Agent runs, newest first"
        columns={columns}
        page={result.data}
        paging="cursor"
        query={paging.query}
        onQueryChange={(next) => paging.onQueryChange(next, result.data?.next_cursor)}
        getRowId={(r) => r.run_id}
        isLoading={result.isPending}
        isFetching={result.isFetching}
        error={result.isError ? result.error.message : null}
        onRetry={() => void result.refetch()}
        onRowClick={(r) => void navigate(`/agents/logs/${r.run_id}`)}
        emptyTitle="No runs match these filters"
        filters={
          <div className="flex flex-wrap items-center gap-3">
            <Select
              label="Agent"
              value={agentKey}
              onChange={reset(setAgentKey)}
              options={(agents.data?.items ?? []).map((a) => ({ value: a.agent_key, label: a.name }))}
            />
            <Select
              label="Status"
              value={status}
              onChange={reset(setStatus)}
              options={RUN_STATUSES.map((s) => ({ value: s, label: RUN_STATUS[s].label }))}
            />
            <Select
              label="Trigger"
              value={trigger}
              onChange={reset(setTrigger)}
              options={TRIGGER_TYPES.map((t) => ({ value: t, label: TRIGGER_LABEL[t] }))}
            />
            <label className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
              From
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => reset(setDateFrom)(e.target.value)}
                className="h-8 rounded-input border border-border px-2 text-xs"
              />
            </label>
            <label className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
              To
              <input
                type="date"
                value={dateTo}
                onChange={(e) => reset(setDateTo)(e.target.value)}
                className="h-8 rounded-input border border-border px-2 text-xs"
              />
            </label>
          </div>
        }
      />
    </div>
  );
}

const STEP_ICON = { TOOL: Wrench, LLM: Sparkles, CHILD_RUN: Bot, ERROR: OctagonAlert, STOP: Square } as const;

function Step({ s }: { s: TraceStepDTO }) {
  const Icon = STEP_ICON[s.kind];
  const ok = ["OK", "SUCCESS"].includes(s.status);
  return (
    <li className="relative border-l-2 border-border pb-3 pl-5">
      <span className="absolute -left-[9px] top-0 flex h-4 w-4 items-center justify-center rounded-full bg-surface">
        <Icon aria-hidden="true" size={13} className={s.kind === "ERROR" ? "text-danger" : "text-ink-secondary"} />
      </span>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-xs font-medium text-ink-secondary">
          {s.kind === "CHILD_RUN"
            ? "Stage"
            : s.kind === "LLM"
              ? "LLM call"
              : s.kind === "STOP"
                ? "Stop"
                : s.kind === "ERROR"
                  ? "Error"
                  : "Tool"}
        </span>
        {s.kind === "CHILD_RUN" && s.run_id ? (
          <Link
            to={`/agents/logs/${s.run_id}`}
            className="font-mono text-[13px] font-semibold text-brand hover:underline"
          >
            {s.name}
          </Link>
        ) : (
          <span className="font-mono text-[13px] font-semibold">{s.name}</span>
        )}
        {s.kind === "CHILD_RUN" || s.kind === "STOP" ? (
          RUN_STATUS[s.status as RunStatus] ? (
            <RunStatusBadge status={s.status as RunStatus} />
          ) : (
            <StatusBadge tone="neutral" label={s.status} />
          )
        ) : (
          <StatusBadge tone={ok ? "success" : s.status === "WARN" ? "warning" : "danger"} label={s.status} />
        )}
        <span className="tabular text-xs text-ink-secondary">
          <When at={s.at} />
          {s.duration_ms !== null && s.duration_ms !== undefined ? ` · ${formatMs(s.duration_ms)}` : ""}
        </span>
      </div>
      {s.model ? (
        <p className="tabular mt-1 text-xs text-ink-secondary">
          {s.model} · in {formatNumber(s.input_tokens ?? 0)} / out {formatNumber(s.output_tokens ?? 0)} tokens ·{" "}
          {formatUsd(s.est_cost_usd)}
        </p>
      ) : null}
      {s.args_summary ? (
        <p className="mt-1 break-all font-mono text-xs text-ink-secondary">args: {s.args_summary}</p>
      ) : null}
      {s.result_summary ? (
        <p className={`mt-1 break-all font-mono text-xs ${s.kind === "ERROR" ? "text-danger" : "text-ink-secondary"}`}>
          {s.kind === "STOP" ? "reason: " : "result: "}
          {s.result_summary}
        </p>
      ) : null}
    </li>
  );
}

export function AgentRunTracePage() {
  const { runId = "" } = useParams();
  const api = useApi();
  const qc = useQueryClient();
  const trace = useAgentRun(runId);
  const [confirm, setConfirm] = useState(false);
  const cancel = useMutation({
    mutationFn: () => api.cancelAgentRun(runId),
    onSuccess: () => {
      setConfirm(false);
      void qc.invalidateQueries({ queryKey: ["agent-run", runId] });
    },
  });

  if (trace.isError) return <ErrorState message={trace.error.message} onRetry={() => void trace.refetch()} />;
  if (trace.isPending)
    return (
      <div aria-label="Loading trace" className="space-y-2">
        <SkeletonLine />
        <SkeletonLine width="60%" />
      </div>
    );
  const t = trace.data;
  const r = t.run;

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(t, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `agent-run-${r.run_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5">
      <Link to="/agents/logs" className="inline-flex items-center gap-1 text-sm text-brand hover:underline">
        <ArrowLeft aria-hidden="true" size={14} /> All runs
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-card border border-border bg-surface p-4 shadow-card">
        <div className="space-y-1">
          <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold text-ink">
            {r.agent_key ? <AgentLink agentKey={r.agent_key} name={r.agent_name} /> : "Nightly pipeline"}
            <RunStatusBadge status={r.status} />
            {r.mode === "DRY_RUN" ? <StatusBadge tone="info" label="Dry run — preview only" /> : null}
            <DemoBadge show={r.is_demo} />
          </h2>
          <p className="font-mono text-xs text-ink-secondary">{r.run_id}</p>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 pt-1 text-sm">
            <div>
              <dt className="inline text-ink-secondary">Trigger: </dt>
              <dd className="inline">{TRIGGER_LABEL[r.trigger_type]}</dd>
            </div>
            <div>
              <dt className="inline text-ink-secondary">Started: </dt>
              <dd className="inline">
                <When at={r.started_at} />
              </dd>
            </div>
            <div>
              <dt className="inline text-ink-secondary">Duration: </dt>
              <dd className="inline tabular">{formatMs(r.duration_ms)}</dd>
            </div>
            <div>
              <dt className="inline text-ink-secondary">Config: </dt>
              <dd className="inline tabular">{t.config_version ? `v${t.config_version}` : "—"}</dd>
            </div>
            <div>
              <dt className="inline text-ink-secondary">Tokens / cost: </dt>
              <dd className="inline tabular">
                {formatNumber(r.tokens)} / {formatUsd(r.est_cost_usd)}
              </dd>
            </div>
            <div>
              <dt className="inline text-ink-secondary">Decisions: </dt>
              <dd className="inline tabular">
                {t.decisions > 0 ? (
                  <Link to={`/agents/decisions?run=${r.run_id}`} className="text-brand hover:underline">
                    {t.decisions}
                  </Link>
                ) : (
                  0
                )}
              </dd>
            </div>
            {r.triggered_by ? (
              <div>
                <dt className="inline text-ink-secondary">By: </dt>
                <dd className="inline">
                  {r.triggered_by}
                  {r.reason ? ` — “${r.reason}”` : ""}
                </dd>
              </div>
            ) : null}
            {r.stop_reason ? (
              <div>
                <dt className="inline text-ink-secondary">Stopping reason: </dt>
                <dd className="inline">{r.stop_reason}</dd>
              </div>
            ) : null}
          </dl>
          {r.error ? (
            <p role="alert" className="mt-2 rounded-input bg-danger-bg px-3 py-2 text-sm text-danger">
              {r.error}
            </p>
          ) : null}
        </div>
        <div className="flex gap-2">
          {r.status === "RUNNING" && r.parent_run_id === null ? (
            <Button variant="destructive" size="sm" icon={<StopCircle size={14} />} onClick={() => setConfirm(true)}>
              Cancel run
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={exportJson}>
            Export JSON
          </Button>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <Panel title={`Timeline (${t.steps.length} steps)`}>
          {t.steps.length ? (
            <ol aria-label="Run timeline">
              {t.steps.map((s, i) => (
                <Step key={`${s.kind}-${i}`} s={s} />
              ))}
            </ol>
          ) : (
            <p className="text-sm text-ink-secondary">No steps recorded.</p>
          )}
        </Panel>
        <div className="space-y-4">
          <Panel title="Input">
            <pre className="max-h-60 overflow-auto whitespace-pre-wrap text-xs">
              {JSON.stringify(t.input_ref, null, 2)}
            </pre>
          </Panel>
          <Panel title="Output summary">
            <pre className="max-h-60 overflow-auto whitespace-pre-wrap text-xs">
              {typeof t.output_summary === "string" ? t.output_summary : JSON.stringify(t.output_summary, null, 2)}
            </pre>
          </Panel>
          {t.previews.length ? (
            <Panel title={`Dry-run preview (${t.previews.length} outputs)`}>
              <p className="mb-2 text-xs text-ink-secondary">
                Never shown in the inbox, purchase orders, transfers or dashboards.
              </p>
              <ul className="max-h-80 space-y-2 overflow-auto">
                {t.previews.map((p, i) => (
                  <li key={i} className="rounded-input border border-divider p-2 text-xs">
                    <span className="font-semibold">
                      {p.agent_key} · {p.output_type}
                    </span>
                    <pre className="mt-1 whitespace-pre-wrap">{JSON.stringify(p.payload, null, 2)}</pre>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
          {t.config_snapshot ? (
            <Panel title="Config snapshot at start">
              <ul className="space-y-0.5 text-xs">
                {Object.entries(t.config_snapshot).map(([k, v]) => (
                  <li key={k} className="flex justify-between gap-2">
                    <span className="font-mono">{k === "__llm__" ? "All LLM agents" : k}</span>
                    <span>{v === true ? "on" : v === false ? "off" : JSON.stringify(v)}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
      <ConfirmDialog
        open={confirm}
        title="Cancel this run?"
        reason="Stop the run after its current step."
        consequences={[
          "The current step finishes; later stages are not started",
          "The run is recorded as CANCELLED",
          "Outputs already written are kept; the next nightly run recalculates",
        ]}
        approver="Super Admin (you)"
        confirmLabel="Cancel run"
        destructive
        onConfirm={() => cancel.mutate()}
        onCancel={() => setConfirm(false)}
      />
    </div>
  );
}
