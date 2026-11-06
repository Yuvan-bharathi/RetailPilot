/** Agents → Pipeline (docs/09 §3.3): root runs over time; expand a run to see each stage in order. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, GitBranch, Play, ScrollText, TriangleAlert } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router";

import { useApi } from "../../app/ApiContext";
import { usePipelineRuns } from "../../api/hooks";
import type { PipelineRunDTO, RunStatus, TriggerType } from "../../api/types";
import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/Modal";
import { EmptyState, ErrorState, SkeletonLine } from "../../components/StateViews";
import { StatusBadge } from "../../components/StatusBadge";
import { DemoBadge, ConsoleTabs, RunStatusBadge, Select, When } from "../../components/agents/agentUi";
import { formatMs, RUN_STATUS, RUN_STATUSES, TRIGGER_LABEL, TRIGGER_TYPES } from "../../lib/agentFormat";
import { useCursorPaging } from "../../lib/useCursorPaging";

function Stages({ run }: { run: PipelineRunDTO }) {
  if (run.stages.length === 0) return <p className="text-sm text-ink-secondary">No stages recorded.</p>;
  return (
    <ol className="space-y-1.5">
      {run.stages.map((s, i) => (
        <li
          key={`${s.agent_key}-${i}`}
          className="grid grid-cols-[2rem_1fr_auto] items-center gap-2 rounded-input border border-divider bg-surface px-3 py-2 text-sm sm:grid-cols-[2rem_14rem_12rem_1fr_auto]"
        >
          <span className="tabular text-xs text-ink-secondary">{i + 1}.</span>
          <Link to={`/agents/${s.agent_key}`} className="font-medium text-brand hover:underline">
            {s.name}
          </Link>
          <RunStatusBadge status={s.status === "NOT_RUN" ? "NOT_RUN" : s.status} />
          <span className="hidden text-xs text-ink-secondary sm:block">
            {formatMs(s.duration_ms)}
            {s.retries ? ` · ${s.retries} retr${s.retries === 1 ? "y" : "ies"}` : ""}
            {s.outputs !== null ? ` · ${s.outputs} outputs` : ""}
            {s.error ? <span className="block text-danger">{s.error}</span> : null}
          </span>
          {s.run_id ? (
            <Link to={`/agents/logs/${s.run_id}`} className="text-xs font-medium text-brand hover:underline">
              Trace
            </Link>
          ) : (
            <span />
          )}
        </li>
      ))}
    </ol>
  );
}

/** Queue the full nightly pipeline (moved here from the former System monitoring page). */
function RunNightlyButton() {
  const api = useApi();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => api.triggerNightlyRun(),
    onSuccess: (r) => {
      setOpen(false);
      setMessage(r.message);
      void qc.invalidateQueries({ queryKey: ["pipeline-runs"] });
    },
    onError: (e: Error) => {
      setOpen(false);
      setMessage(`Could not queue the nightly run: ${e.message}`);
    },
  });
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button icon={<Play size={15} />} onClick={() => setOpen(true)} disabled={mutation.isPending}>
        Run nightly pipeline
      </Button>
      {message ? (
        <span role="status" className="text-sm text-ink-secondary">
          {message}
        </span>
      ) : null}
      <ConfirmDialog
        open={open}
        title="Run the nightly pipeline now?"
        reason="Plan the next business day with the latest loaded data."
        consequences={[
          "All enabled stages run in order with the current configuration",
          "Untouched recommendations, PROPOSED transfers and undecided PENDING_L1 POs of earlier runs are superseded",
          "New recommendations and POs reach the inbox for approval",
        ]}
        approver="Super Admin (you); recommendations then go to store supervisors"
        confirmLabel="Run nightly pipeline"
        onConfirm={() => mutation.mutate()}
        onCancel={() => setOpen(false)}
      />
    </div>
  );
}

export function AgentPipelinePage() {
  const paging = useCursorPaging(20);
  const [trigger, setTrigger] = useState<TriggerType | "">("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const result = usePipelineRuns({
    cursor: paging.cursor,
    page_size: paging.query.pageSize,
    trigger_type: trigger || undefined,
    status: status || undefined,
  });
  const rows = result.data?.items ?? [];

  return (
    <div className="space-y-5">
      <ConsoleTabs />
      <RunNightlyButton />
      <div className="flex flex-wrap items-center gap-3">
        <Select
          label="Trigger"
          value={trigger}
          onChange={(v) => {
            setTrigger(v);
            paging.reset();
          }}
          options={TRIGGER_TYPES.map((t) => ({ value: t, label: TRIGGER_LABEL[t] }))}
        />
        <Select
          label="Status"
          value={status}
          onChange={(v) => {
            setStatus(v);
            paging.reset();
          }}
          options={RUN_STATUSES.map((s) => ({ value: s, label: RUN_STATUS[s].label }))}
        />
      </div>
      <div className="relative overflow-x-auto rounded-card border border-border bg-surface shadow-card">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Pipeline runs, newest first</caption>
          <thead className="border-b border-border bg-elevated text-xs text-ink-secondary">
            <tr>
              <th className="w-10 px-3 py-2">
                <span className="sr-only">Expand</span>
              </th>
              <th className="px-3 py-2">Run date</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Trigger</th>
              <th className="px-3 py-2">Started</th>
              <th className="px-3 py-2 text-right">Duration</th>
              <th className="px-3 py-2">Config</th>
              <th className="px-3 py-2">Attention</th>
              <th className="px-3 py-2">
                <span className="sr-only">Links</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {result.isPending ? (
              <tr>
                <td colSpan={9} className="p-4">
                  <SkeletonLine />
                </td>
              </tr>
            ) : result.isError ? (
              <tr>
                <td colSpan={9}>
                  <ErrorState message={result.error.message} onRetry={() => void result.refetch()} />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={9}>
                  <EmptyState
                    title="No runs yet"
                    description="Runs appear after the nightly pipeline or a manual trigger."
                  />
                </td>
              </tr>
            ) : (
              rows.map((r) => {
                const isOpen = open[r.run_id] ?? false;
                const attention = r.escalations > 0 || r.has_partial || r.status === "FAILED" || r.status === "PAUSED";
                return (
                  <Fragment key={r.run_id}>
                    <tr className={`border-b border-divider ${attention ? "bg-warning-bg/40" : ""}`}>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          aria-label={`${isOpen ? "Collapse" : "Expand"} stages of run ${r.run_date ?? r.run_id}`}
                          onClick={() => setOpen((o) => ({ ...o, [r.run_id]: !isOpen }))}
                          className="rounded p-1 text-ink-secondary hover:bg-elevated"
                        >
                          {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        </button>
                      </td>
                      <td className="tabular px-3 py-2 font-medium">{r.run_date ?? "—"}</td>
                      <td className="px-3 py-2">
                        <RunStatusBadge status={r.status} />
                      </td>
                      <td className="px-3 py-2">
                        {TRIGGER_LABEL[r.trigger_type]} <DemoBadge show={r.is_demo} />
                        {r.agent_key ? <span className="block text-xs text-ink-secondary">{r.agent_key}</span> : null}
                      </td>
                      <td className="px-3 py-2">
                        <When at={r.started_at} />
                      </td>
                      <td className="tabular px-3 py-2 text-right">{formatMs(r.duration_ms)}</td>
                      <td className="tabular px-3 py-2 text-xs">{r.config_version ? `v${r.config_version}` : "—"}</td>
                      <td className="px-3 py-2">
                        {r.escalations > 0 ? (
                          <StatusBadge tone="danger" label={`${r.escalations} escalation(s)`} icon={TriangleAlert} />
                        ) : r.has_partial ? (
                          <StatusBadge tone="warning" label="Partial results" />
                        ) : (
                          <span className="text-xs text-ink-secondary">—</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs">
                        <Link
                          to={`/agents/flow?run=${r.run_id}`}
                          className="mr-3 inline-flex items-center gap-1 font-medium text-brand hover:underline"
                        >
                          <GitBranch aria-hidden="true" size={13} /> Flow
                        </Link>
                        <Link
                          to={`/agents/logs/${r.run_id}`}
                          className="inline-flex items-center gap-1 font-medium text-brand hover:underline"
                        >
                          <ScrollText aria-hidden="true" size={13} /> Trace
                        </Link>
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr className="border-b border-divider bg-app">
                        <td />
                        <td colSpan={8} className="px-3 py-3">
                          {r.reason ? <p className="mb-2 text-xs text-ink-secondary">Reason: {r.reason}</p> : null}
                          <Stages run={r} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={paging.query.page <= 1}
          onClick={() => paging.onQueryChange({ ...paging.query, page: paging.query.page - 1 }, null)}
        >
          Previous
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={!result.data?.next_cursor}
          onClick={() =>
            paging.onQueryChange({ ...paging.query, page: paging.query.page + 1 }, result.data?.next_cursor)
          }
        >
          Next
        </Button>
      </div>
    </div>
  );
}
