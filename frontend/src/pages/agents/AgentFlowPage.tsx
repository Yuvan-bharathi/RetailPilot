/** Agents → Visual flow (docs/09 §3.4): the graph of one run; polls every 5 s while it is in progress. */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { usePipelineRuns, useRunGraph } from "../../api/hooks";
import type { GraphNodeDTO } from "../../api/types";
import { ErrorState, SkeletonLine } from "../../components/StateViews";
import { AgentFlowGraph } from "../../components/agents/AgentFlowGraph";
import { ConsoleTabs, Panel, RunStatusBadge } from "../../components/agents/agentUi";
import { TRIGGER_LABEL } from "../../lib/agentFormat";

export function AgentFlowPage() {
  const [params, setParams] = useSearchParams();
  const runs = usePipelineRuns({ page_size: 30 });
  const requested = params.get("run");
  const runId = requested ?? runs.data?.items[0]?.run_id ?? null;
  const graph = useRunGraph(runId);
  const [selected, setSelected] = useState<GraphNodeDTO | null>(null);

  return (
    <div className="space-y-5">
      <ConsoleTabs />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
          Run
          <select
            className="h-8 max-w-md rounded-input border border-border bg-surface px-2 text-xs text-ink"
            value={runId ?? ""}
            onChange={(e) => {
              setSelected(null);
              setParams({ run: e.target.value });
            }}
          >
            {(runs.data?.items ?? []).map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_date ?? "—"} · {TRIGGER_LABEL[r.trigger_type]}
                {r.agent_key ? ` (${r.agent_key})` : ""} · {r.status}
              </option>
            ))}
          </select>
        </label>
        {graph.data ? <RunStatusBadge status={graph.data.status} /> : null}
        {graph.data?.in_progress ? (
          <span role="status" className="text-xs text-ink-secondary">
            Run in progress — updating every 5 seconds
          </span>
        ) : null}
      </div>
      {runs.isError ? (
        <ErrorState message={runs.error.message} onRetry={() => void runs.refetch()} />
      ) : graph.isError ? (
        <ErrorState message={graph.error.message} onRetry={() => void graph.refetch()} />
      ) : !runId && !runs.isPending ? (
        <p className="text-sm text-ink-secondary">No runs yet.</p>
      ) : graph.isPending ? (
        <div aria-label="Loading graph" className="space-y-2">
          <SkeletonLine />
          <SkeletonLine width="50%" />
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
          <AgentFlowGraph
            nodes={graph.data.nodes}
            edges={graph.data.edges}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
          />
          <Panel title={selected ? selected.label : "Select a node"}>
            {selected ? (
              <div className="space-y-2 text-sm">
                <RunStatusBadge status={selected.status ?? "NOT_RUN"} />
                {selected.detail ? <p className="text-ink-secondary">{selected.detail}</p> : null}
                {selected.node_type === "GATE" ? (
                  <p className="text-ink-secondary">
                    People decide here: L1/L2 PO approval, transfer acceptance and release. No agent can pass this gate.
                  </p>
                ) : null}
                {selected.run_id ? (
                  <Link to={`/agents/logs/${selected.run_id}`} className="block font-medium text-brand hover:underline">
                    Open run trace
                  </Link>
                ) : null}
                {selected.agent_key ? (
                  <Link to={`/agents/${selected.agent_key}`} className="block font-medium text-brand hover:underline">
                    Agent details
                  </Link>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-ink-secondary">
                Click an agent to see its status and open its run trace. Edges show data hand-offs, the reviewer before
                the inbox, the coordinator on exceptions and the human approval gate.
              </p>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
