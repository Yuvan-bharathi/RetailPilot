/** Agents → Decisions (docs/09 §3.7): every decision any agent took, with evidence link and human outcome. */
import { useDeferredValue, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useAgents, useDecisions, useDecisionStats, useStores } from "../../api/hooks";
import type { AgentDecisionDTO, DecisionOutcome, RunMode } from "../../api/types";
import { DataTable, type Column } from "../../components/DataTable";
import { ErrorState } from "../../components/StateViews";
import { StatusBadge } from "../../components/StatusBadge";
import { AgentLink, ConsoleTabs, OutcomeBadge, Panel, Select, When } from "../../components/agents/agentUi";
import { decisionLabel, formatRate, OUTCOMES } from "../../lib/agentFormat";
import { useCursorPaging } from "../../lib/useCursorPaging";

const OUTCOME_LABEL: Record<DecisionOutcome, string> = {
  PENDING: "Pending",
  ACCEPTED: "Accepted",
  EDITED: "Edited",
  REJECTED: "Rejected",
  SUPERSEDED: "Superseded",
  NOT_APPLICABLE: "No action needed",
};

function evidenceLink(d: AgentDecisionDTO) {
  if (d.rec_id) return <Link to={`/recommendations/${d.rec_id}`}>Recommendation</Link>;
  if (d.transfer_id) return <Link to="/transfers">Transfer</Link>;
  if (d.po_id) return <Link to="/purchase-orders">Purchase order</Link>;
  return <Link to={`/agents/logs/${d.run_id}`}>Run trace</Link>;
}

export function AgentDecisionsPage() {
  const [params] = useSearchParams();
  const runId = params.get("run");
  const paging = useCursorPaging(25);
  const agents = useAgents();
  const stores = useStores();
  const [agentKey, setAgentKey] = useState("");
  const [decisionType, setDecisionType] = useState("");
  const [outcome, setOutcome] = useState<DecisionOutcome | "">("");
  const [mode, setMode] = useState<RunMode | "">("");
  const [storeId, setStoreId] = useState("");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const stats = useDecisionStats(agentKey || undefined);
  const result = useDecisions({
    cursor: paging.cursor,
    page_size: paging.query.pageSize,
    agent_key: agentKey || undefined,
    decision_type: decisionType || undefined,
    outcome: outcome || undefined,
    mode: mode || undefined,
    store_id: storeId || undefined,
    run_id: runId ?? undefined,
    q: q || undefined,
  });
  const reset =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      paging.reset();
    };
  const types = [...new Set((stats.data ?? []).map((s) => s.decision_type))].sort();

  const columns: Column<AgentDecisionDTO>[] = [
    { id: "created_at", header: "Time", cell: (d) => <When at={d.created_at} /> },
    { id: "agent", header: "Agent", cell: (d) => <AgentLink agentKey={d.agent_key} name={d.agent_name} /> },
    {
      id: "type",
      header: "Decision",
      cell: (d) => (
        <span>
          {decisionLabel(d.decision_type)}
          {d.mode === "DRY_RUN" ? (
            <span className="ml-1">
              <StatusBadge tone="info" label="Dry run" />
            </span>
          ) : null}
        </span>
      ),
    },
    { id: "store", header: "Store", cell: (d) => d.store?.name ?? "—" },
    { id: "product", header: "Product", cell: (d) => d.product?.name ?? "—" },
    { id: "summary", header: "Summary", cell: (d) => d.summary },
    {
      id: "evidence",
      header: "Evidence",
      cell: (d) => <span className="font-medium text-brand hover:underline">{evidenceLink(d)}</span>,
    },
    {
      id: "outcome",
      header: "Human outcome",
      cell: (d) => (
        <span>
          <OutcomeBadge outcome={d.outcome} />
          {d.outcome_reason ? <span className="block text-xs text-ink-secondary">“{d.outcome_reason}”</span> : null}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <ConsoleTabs />
      <Panel title="Acceptance by agent and decision type (live decisions)">
        {stats.isError ? (
          <ErrorState message={stats.error.message} onRetry={() => void stats.refetch()} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Acceptance rate per agent and decision type</caption>
              <thead className="border-b border-border text-xs text-ink-secondary">
                <tr>
                  <th className="px-2 py-2">Agent</th>
                  <th className="px-2 py-2">Decision</th>
                  <th className="px-2 py-2 text-right">Total</th>
                  <th className="px-2 py-2 text-right">Accepted</th>
                  <th className="px-2 py-2 text-right">Edited</th>
                  <th className="px-2 py-2 text-right">Rejected</th>
                  <th className="px-2 py-2 text-right">Pending</th>
                  <th className="px-2 py-2 text-right">Acceptance</th>
                </tr>
              </thead>
              <tbody>
                {(stats.data ?? []).map((s) => (
                  <tr key={`${s.agent_key}-${s.decision_type}`} className="border-b border-divider">
                    <td className="px-2 py-1.5">{s.agent_key}</td>
                    <td className="px-2 py-1.5">{decisionLabel(s.decision_type)}</td>
                    <td className="tabular px-2 py-1.5 text-right">{s.total}</td>
                    <td className="tabular px-2 py-1.5 text-right">{s.accepted}</td>
                    <td className="tabular px-2 py-1.5 text-right">{s.edited}</td>
                    <td className="tabular px-2 py-1.5 text-right">{s.rejected}</td>
                    <td className="tabular px-2 py-1.5 text-right">{s.pending}</td>
                    <td className="tabular px-2 py-1.5 text-right font-semibold">{formatRate(s.acceptance_rate)}</td>
                  </tr>
                ))}
                {stats.data?.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-2 py-4 text-center text-ink-secondary">
                      No decisions yet
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {runId ? (
        <p className="text-sm text-ink-secondary">
          Showing decisions of run <span className="font-mono">{runId}</span> ·{" "}
          <Link to="/agents/decisions" className="text-brand hover:underline">
            show all
          </Link>
        </p>
      ) : null}
      <DataTable
        caption="Agent decisions, newest first"
        columns={columns}
        page={result.data}
        paging="cursor"
        query={paging.query}
        onQueryChange={(next) => paging.onQueryChange(next, result.data?.next_cursor)}
        getRowId={(d) => d.decision_id}
        isLoading={result.isPending}
        isFetching={result.isFetching}
        error={result.isError ? result.error.message : null}
        onRetry={() => void result.refetch()}
        search={{ value: search, onChange: reset(setSearch), placeholder: "Search summary or product" }}
        emptyTitle="No decisions match these filters"
        filters={
          <div className="flex flex-wrap items-center gap-3">
            <Select
              label="Agent"
              value={agentKey}
              onChange={reset(setAgentKey)}
              options={(agents.data?.items ?? []).map((a) => ({ value: a.agent_key, label: a.name }))}
            />
            <Select
              label="Decision"
              value={decisionType}
              onChange={reset(setDecisionType)}
              options={types.map((t) => ({ value: t, label: decisionLabel(t) }))}
            />
            <Select
              label="Outcome"
              value={outcome}
              onChange={reset(setOutcome)}
              options={OUTCOMES.map((o) => ({ value: o, label: OUTCOME_LABEL[o] }))}
            />
            <Select
              label="Mode"
              value={mode}
              onChange={reset(setMode)}
              options={[
                { value: "LIVE" as RunMode, label: "Live" },
                { value: "DRY_RUN" as RunMode, label: "Dry run" },
              ]}
            />
            <Select
              label="Store"
              value={storeId}
              onChange={reset(setStoreId)}
              options={(stores.data ?? []).map((s) => ({ value: s.store_id, label: s.name }))}
            />
          </div>
        }
      />
    </div>
  );
}
