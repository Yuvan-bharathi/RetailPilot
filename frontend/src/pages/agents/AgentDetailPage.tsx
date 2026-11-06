/** Agents → Agent detail (docs/09 §3.2): card, 4D notes, contracts, tools, stopping conditions, runs, decisions,
 * evaluations, "Run now" and toggle history. Parameters are read-only here (edit in Settings → business rules). */
import { ArrowLeft, ShieldAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useAgent, useAgentRuns, useDecisions } from "../../api/hooks";
import type { AgentDetailDTO, AgentRunItemDTO, AgentDecisionDTO } from "../../api/types";
import { DataTable, type Column } from "../../components/DataTable";
import { ErrorState, SkeletonLine } from "../../components/StateViews";
import { StatusBadge } from "../../components/StatusBadge";
import { Tabs } from "../../components/Tabs";
import { RunNowPanel, ToggleAgentButton } from "../../components/agents/AgentControls";
import { MarkdownLite } from "../../components/agents/MarkdownLite";
import { DemoBadge, KindBadge, OutcomeBadge, Panel, RunStatusBadge, When } from "../../components/agents/agentUi";
import { decisionLabel, formatMs, formatRate, formatUsd, PATTERN_LABEL, TRIGGER_LABEL } from "../../lib/agentFormat";
import { useCursorPaging } from "../../lib/useCursorPaging";
import { formatNumber } from "../../lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-ink-secondary">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}

function CardTab({ d }: { d: AgentDetailDTO }) {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Panel title="4D — how this agent is delegated and controlled">
        <dl className="space-y-3">
          <Field label="Delegation — why an agent (or why not)">{d.delegation}</Field>
          <Field label="Description — instructions and contracts">{d.description}</Field>
          <Field label="Discernment — how output is judged">{d.discernment}</Field>
          <Field label="Diligence — approvals, logging, accountability">{d.diligence}</Field>
        </dl>
      </Panel>
      <Panel title="Contract and limits">
        <dl className="space-y-3">
          <Field label="Input">{d.input_contract}</Field>
          <Field label="Output">{d.output_contract}</Field>
          <Field label="Read tools">
            {d.read_tools.length ? (
              <ul className="flex flex-wrap gap-1">
                {d.read_tools.map((t) => (
                  <li key={t}>
                    <code className="rounded bg-info-bg px-1.5 py-0.5 text-xs text-info">{t}</code>
                  </li>
                ))}
              </ul>
            ) : (
              "—"
            )}
          </Field>
          <Field label="Draft-write tools (never approve, submit, dispatch or change stock)">
            {d.draft_tools.length ? (
              <ul className="flex flex-wrap gap-1">
                {d.draft_tools.map((t) => (
                  <li key={t}>
                    <code className="rounded bg-attention-bg px-1.5 py-0.5 text-xs text-attention">{t}</code>
                  </li>
                ))}
              </ul>
            ) : (
              "None"
            )}
          </Field>
          <Field label="Stopping conditions">
            <ul className="list-disc pl-5">
              {d.stopping.max_tool_calls !== null ? <li>max {d.stopping.max_tool_calls} tool calls</li> : null}
              {d.stopping.max_tokens !== null ? <li>max {formatNumber(d.stopping.max_tokens)} tokens</li> : null}
              {d.stopping.timeout_s !== null ? <li>timeout {d.stopping.timeout_s} s</li> : null}
              {d.stopping.other.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
          </Field>
          <Field label="When turned off">{d.disabled_effect}</Field>
          <Field label="Human in the loop">{d.human_in_the_loop}</Field>
          <Field label="Parameters (edit in Settings → business rules)">
            {d.business_rules.length ? (
              <ul className="space-y-0.5">
                {d.business_rules.map((r) => (
                  <li key={r.key}>
                    <code className="text-xs">{r.key}</code> ={" "}
                    <span className="tabular">{JSON.stringify(r.value)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              "None"
            )}
          </Field>
        </dl>
      </Panel>
      {d.prompt_text ? (
        <Panel title={`System instructions — ${d.prompt_version}`} className="xl:col-span-2">
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-input bg-neutral-bg p-3 text-xs">
            {d.prompt_text}
          </pre>
        </Panel>
      ) : null}
      {d.card_markdown ? (
        <Panel title="Agent card" className="xl:col-span-2">
          <MarkdownLite source={d.card_markdown} />
        </Panel>
      ) : null}
    </div>
  );
}

function RunsTab({ agentKey }: { agentKey: string }) {
  const paging = useCursorPaging(10);
  const navigate = useNavigate();
  const result = useAgentRuns({ agent_key: agentKey, cursor: paging.cursor, page_size: paging.query.pageSize });
  const columns: Column<AgentRunItemDTO>[] = [
    { id: "started_at", header: "Started", cell: (r) => <When at={r.started_at} /> },
    { id: "status", header: "Status", cell: (r) => <RunStatusBadge status={r.status} /> },
    { id: "trigger", header: "Trigger", cell: (r) => TRIGGER_LABEL[r.trigger_type] },
    { id: "duration", header: "Duration", cell: (r) => formatMs(r.duration_ms), align: "right" },
    { id: "tools", header: "Tool calls", cell: (r) => r.tool_calls, align: "right" },
    { id: "tokens", header: "Tokens", cell: (r) => formatNumber(r.tokens), align: "right" },
    { id: "stop", header: "Stop reason", cell: (r) => r.error ?? r.stop_reason ?? "—" },
  ];
  return (
    <DataTable
      caption="Recent runs of this agent"
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
      emptyTitle="No runs yet"
    />
  );
}

function DecisionsTab({ agentKey }: { agentKey: string }) {
  const paging = useCursorPaging(10);
  const result = useDecisions({ agent_key: agentKey, cursor: paging.cursor, page_size: paging.query.pageSize });
  const columns: Column<AgentDecisionDTO>[] = [
    { id: "created_at", header: "Time", cell: (d) => <When at={d.created_at} /> },
    { id: "type", header: "Decision", cell: (d) => decisionLabel(d.decision_type) },
    { id: "store", header: "Store", cell: (d) => d.store?.name ?? "—" },
    { id: "summary", header: "Summary", cell: (d) => d.summary },
    { id: "outcome", header: "Outcome", cell: (d) => <OutcomeBadge outcome={d.outcome} /> },
  ];
  return (
    <DataTable
      caption="Recent decisions of this agent"
      columns={columns}
      page={result.data}
      paging="cursor"
      query={paging.query}
      onQueryChange={(next) => paging.onQueryChange(next, result.data?.next_cursor)}
      getRowId={(d) => d.decision_id}
      isLoading={result.isPending}
      isFetching={result.isFetching}
      error={result.isError ? result.error.message : null}
      emptyTitle="No decisions yet"
    />
  );
}

function EvalsTab({ d }: { d: AgentDetailDTO }) {
  if (d.evals.length === 0) {
    return (
      <p className="text-sm text-ink-secondary">
        {d.agent.kind === "DETERMINISTIC"
          ? "Deterministic stage: judged by unit, property and scenario tests (listed in the agent card → Evaluation), not by the LLM evaluation harness."
          : "No evaluation results recorded yet — run python -m scripts.run_agent_evals."}
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Latest evaluation results</caption>
        <thead className="border-b border-border text-xs text-ink-secondary">
          <tr>
            <th className="px-2 py-2">Variant</th>
            <th className="px-2 py-2">Source</th>
            <th className="px-2 py-2 text-right">Cases</th>
            <th className="px-2 py-2 text-right">Correct</th>
            <th className="px-2 py-2 text-right">Grounded</th>
            <th className="px-2 py-2 text-right">Tool use</th>
            <th className="px-2 py-2 text-right">Failure handling</th>
            <th className="px-2 py-2 text-right">p50 / p95</th>
            <th className="px-2 py-2 text-right">Tokens / cost</th>
            <th className="px-2 py-2 text-right">Human agreement</th>
          </tr>
        </thead>
        <tbody>
          {d.evals.map((e) => (
            <tr key={`${e.variant}-${e.created_at}`} className="border-b border-divider">
              <td className="px-2 py-2">
                <StatusBadge
                  tone={e.variant === "AGENT" ? "info" : "neutral"}
                  label={e.variant === "AGENT" ? "Agent" : "Deterministic baseline"}
                />
              </td>
              <td className="px-2 py-2">{e.source === "RECORDED" ? "Recorded (CI)" : "Live"}</td>
              <td className="tabular px-2 py-2 text-right">{e.cases}</td>
              <td className="tabular px-2 py-2 text-right">{formatRate(e.correctness)}</td>
              <td className="tabular px-2 py-2 text-right">{formatRate(e.groundedness)}</td>
              <td className="tabular px-2 py-2 text-right">{formatRate(e.tool_use)}</td>
              <td className="tabular px-2 py-2 text-right">{formatRate(e.failure_handling)}</td>
              <td className="tabular px-2 py-2 text-right">
                {formatMs(e.latency_p50_ms)} / {formatMs(e.latency_p95_ms)}
              </td>
              <td className="tabular px-2 py-2 text-right">
                {formatNumber(e.tokens)} / {formatUsd(e.est_cost_usd)}
              </td>
              <td className="tabular px-2 py-2 text-right">{formatRate(e.human_agreement)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-secondary">
        Full report: docs/notes/agent-eval-report.md · comparison: docs/notes/agent-pattern-comparison.md
      </p>
    </div>
  );
}

function HistoryTab({ d }: { d: AgentDetailDTO }) {
  return d.toggle_history.length === 0 ? (
    <p className="text-sm text-ink-secondary">No changes.</p>
  ) : (
    <ol className="space-y-2">
      {d.toggle_history.map((h) => (
        <li key={h.config_version} className="rounded-input border border-divider p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="tabular text-xs text-ink-secondary">v{h.config_version}</span>
            <span className="font-medium">{h.agent_key ? "This agent" : "All LLM agents"}</span>
            <DemoBadge show={h.is_demo} />
            <span>
              {h.previous_enabled === null ? "" : h.previous_enabled ? "on → " : "off → "}
              <strong>{h.enabled ? "on" : "off"}</strong>
            </span>
            <span className="text-ink-secondary">
              by {h.updated_by ?? "system"} · <When at={h.created_at} />
            </span>
          </div>
          <p className="mt-1 text-ink-secondary">“{h.reason}”</p>
        </li>
      ))}
    </ol>
  );
}

export function AgentDetailPage() {
  const { agentKey = "" } = useParams();
  const agent = useAgent(agentKey);
  const [tab, setTab] = useState("card");

  if (agent.isError) return <ErrorState message={agent.error.message} onRetry={() => void agent.refetch()} />;
  if (agent.isPending)
    return (
      <div className="space-y-3" aria-label="Loading agent">
        <SkeletonLine />
        <SkeletonLine width="70%" />
      </div>
    );
  const d = agent.data;
  const a = d.agent;

  return (
    <div className="space-y-5">
      <Link to="/agents" className="inline-flex items-center gap-1 text-sm text-brand hover:underline">
        <ArrowLeft aria-hidden="true" size={14} /> All agents
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-card border border-border bg-surface p-4 shadow-card">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-ink">{a.name}</h2>
          <p className="max-w-3xl text-sm text-ink-secondary">{a.purpose}</p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <KindBadge kind={a.kind} />
            <StatusBadge tone="neutral" label={PATTERN_LABEL[a.pattern]} />
            {a.critical ? <StatusBadge tone="attention" label="Critical" icon={ShieldAlert} /> : null}
            <StatusBadge
              tone={a.effective_enabled ? "success" : "neutral"}
              label={a.effective_enabled ? "On" : a.enabled ? "Off (LLM switch)" : "Off"}
            />
            {a.last_run ? <RunStatusBadge status={a.last_run.status} /> : null}
            {d.prompt_version ? <code className="text-xs text-ink-secondary">{d.prompt_version}</code> : null}
          </div>
        </div>
        <ToggleAgentButton agent={a} />
      </div>
      <Tabs
        label="Agent sections"
        value={tab}
        onChange={setTab}
        items={[
          { key: "card", label: "Card" },
          { key: "run", label: "Run now" },
          { key: "runs", label: "Runs" },
          { key: "decisions", label: "Decisions" },
          { key: "evals", label: "Evaluation" },
          { key: "history", label: "Toggle history" },
        ]}
      >
        {tab === "card" ? <CardTab d={d} /> : null}
        {tab === "run" ? (
          <Panel title="Run now">
            <RunNowPanel agent={a} />
          </Panel>
        ) : null}
        {tab === "runs" ? <RunsTab agentKey={a.agent_key} /> : null}
        {tab === "decisions" ? <DecisionsTab agentKey={a.agent_key} /> : null}
        {tab === "evals" ? <EvalsTab d={d} /> : null}
        {tab === "history" ? <HistoryTab d={d} /> : null}
      </Tabs>
    </div>
  );
}
