/** Agents → Overview (docs/09 §3.1): one card per registered agent, toggles and the global LLM switch. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, ArrowRight, ShieldAlert, Sparkles } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";

import { useApi } from "../../app/ApiContext";
import { useAgents } from "../../api/hooks";
import type { AgentSummaryDTO } from "../../api/types";
import { Button } from "../../components/Button";
import { KpiCard } from "../../components/KpiCard";
import { Modal } from "../../components/Modal";
import { ErrorState, SkeletonLine } from "../../components/StateViews";
import { StatusBadge } from "../../components/StatusBadge";
import { ToggleAgentButton } from "../../components/agents/AgentControls";
import { ConsoleTabs, KindBadge, RunStatusBadge, When } from "../../components/agents/agentUi";
import { formatMs, formatRate, formatUsd, PATTERN_LABEL } from "../../lib/agentFormat";
import { formatNumber } from "../../lib/format";

function AgentCard({ agent }: { agent: AgentSummaryDTO }) {
  return (
    <article
      aria-label={agent.name}
      className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4 shadow-card"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-ink">
            <Link to={`/agents/${agent.agent_key}`} className="hover:underline">
              {agent.name}
            </Link>
          </h3>
          <p className="text-xs text-ink-secondary">{PATTERN_LABEL[agent.pattern]}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-1">
          <KindBadge kind={agent.kind} />
          {agent.critical ? <StatusBadge tone="attention" label="Critical" icon={ShieldAlert} /> : null}
        </div>
      </div>
      <p className="text-sm text-ink-secondary">{agent.purpose}</p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {agent.effective_enabled ? (
          <StatusBadge tone="success" label="On" />
        ) : agent.enabled ? (
          <StatusBadge tone="warning" label="Off — all LLM agents switched off" />
        ) : (
          <StatusBadge tone="neutral" label="Off" />
        )}
        {agent.last_run ? (
          <>
            <RunStatusBadge status={agent.last_run.status} />
            <span className="text-ink-secondary">
              <When at={agent.last_run.started_at} />
            </span>
          </>
        ) : (
          <span className="text-ink-secondary">No runs yet</span>
        )}
      </div>
      {agent.depends_on.length || agent.optional_inputs.length ? (
        <p className="text-xs text-ink-secondary">
          Needs: {agent.depends_on.join(", ") || "—"}
          {agent.optional_inputs.length ? ` · uses if present: ${agent.optional_inputs.join(", ")}` : ""}
        </p>
      ) : null}
      <dl className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-ink-secondary">Success 7d</dt>
          <dd className="tabular font-semibold text-ink">{formatRate(agent.success_rate_7d)}</dd>
        </div>
        <div>
          <dt className="text-ink-secondary">p95 latency</dt>
          <dd className="tabular font-semibold text-ink">{formatMs(agent.p95_latency_ms)}</dd>
        </div>
        <div>
          <dt className="text-ink-secondary">Runs 7d</dt>
          <dd className="tabular font-semibold text-ink">{agent.runs_7d}</dd>
        </div>
        {agent.kind === "LLM" ? (
          <>
            <div>
              <dt className="text-ink-secondary">Tokens 7d</dt>
              <dd className="tabular font-semibold text-ink">{formatNumber(agent.tokens_7d)}</dd>
            </div>
            <div>
              <dt className="text-ink-secondary">Est. cost 7d</dt>
              <dd className="tabular font-semibold text-ink">{formatUsd(agent.est_cost_7d_usd)}</dd>
            </div>
          </>
        ) : null}
        <div>
          <dt className="text-ink-secondary">Decisions 7d</dt>
          <dd className="tabular font-semibold text-ink">{agent.recommendations_7d}</dd>
        </div>
        <div>
          <dt className="text-ink-secondary">Accepted by people</dt>
          <dd className="tabular font-semibold text-ink">{formatRate(agent.acceptance_rate)}</dd>
        </div>
      </dl>
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-divider pt-3">
        <ToggleAgentButton agent={agent} />
        <Link
          to={`/agents/${agent.agent_key}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
        >
          Details <ArrowRight aria-hidden="true" size={14} />
        </Link>
      </div>
    </article>
  );
}

function LlmSwitch({ enabled }: { enabled: boolean }) {
  const api = useApi();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const id = useId();
  const mutation = useMutation({
    mutationFn: () => api.toggleLlmAgents({ enabled: !enabled, reason: reason.trim() }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      setTouched(false);
      void qc.invalidateQueries({ queryKey: ["agents"] });
      void qc.invalidateQueries({ queryKey: ["agent"] });
    },
  });
  const missing = reason.trim().length < 5;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-card border border-border bg-surface px-4 py-3 shadow-card">
      <Sparkles aria-hidden="true" size={18} className="text-brand" />
      <div className="mr-auto">
        <p className="text-sm font-semibold text-ink">All LLM agents</p>
        <p className="text-xs text-ink-secondary">
          Cost and safety kill switch. When off, LLM agents do not run and explanations use templates.
        </p>
      </div>
      <StatusBadge tone={enabled ? "success" : "neutral"} label={enabled ? "On" : "Off"} />
      <Button size="sm" variant={enabled ? "destructive" : "secondary"} onClick={() => setOpen(true)}>
        {enabled ? "Switch all off" : "Switch all on"}
      </Button>
      <Modal
        open={open}
        title={enabled ? "Switch off all LLM agents?" : "Switch on all LLM agents?"}
        description="Takes effect from the next run."
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={enabled ? "destructive" : "primary"}
              onClick={() => {
                setTouched(true);
                if (!missing) mutation.mutate();
              }}
            >
              Confirm
            </Button>
          </>
        }
      >
        <label htmlFor={id} className="text-sm font-medium">
          Reason <span className="text-danger">*</span>
        </label>
        <textarea
          id={id}
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={touched && missing}
          className="mt-1 w-full rounded-input border border-border p-2 text-sm"
        />
        {touched && missing ? <p className="text-xs text-danger">Enter a reason (5+ characters).</p> : null}
        {mutation.isError ? (
          <p role="alert" className="text-sm text-danger">
            {mutation.error.message}
          </p>
        ) : null}
      </Modal>
    </div>
  );
}

export function AgentsOverviewPage() {
  const agents = useAgents();
  const items = agents.data?.items ?? [];
  const pipeline = items.filter((a) => a.group === "PIPELINE");
  const objective = items.filter((a) => a.group === "OBJECTIVE_III");
  const llm = items.filter((a) => a.kind === "LLM");

  return (
    <div className="space-y-5">
      <ConsoleTabs />
      {agents.isError ? (
        <ErrorState message={agents.error.message} onRetry={() => void agents.refetch()} />
      ) : agents.isPending ? (
        <div className="space-y-3" aria-label="Loading agents">
          <SkeletonLine />
          <SkeletonLine width="60%" />
        </div>
      ) : (
        <>
          {agents.data.paused_banner ? (
            <div role="alert" className="flex items-center gap-2 rounded-card bg-attention-bg px-4 py-3 text-attention">
              <AlertOctagon aria-hidden="true" size={18} />
              <span className="font-medium">{agents.data.paused_banner}</span>
            </div>
          ) : null}
          <h2 className="sr-only">Summary</h2>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              title="Agents on"
              value={`${items.filter((a) => a.effective_enabled).length} of ${items.length}`}
              meta={`config v${agents.data.config_version}`}
            />
            <KpiCard title="Runs (7 days)" value={formatNumber(items.reduce((s, a) => s + a.runs_7d, 0))} />
            <KpiCard
              title="LLM tokens (7 days)"
              value={formatNumber(llm.reduce((s, a) => s + a.tokens_7d, 0))}
              meta={formatUsd(llm.reduce((s, a) => s + Number(a.est_cost_7d_usd), 0))}
            />
            <KpiCard
              title="Decisions (7 days)"
              value={formatNumber(items.reduce((s, a) => s + a.recommendations_7d, 0))}
            />
          </div>
          <LlmSwitch enabled={agents.data.llm_enabled} />
          <section aria-labelledby="pipeline-agents" className="space-y-3">
            <h2 id="pipeline-agents" className="text-base font-semibold text-ink">
              Nightly pipeline — deterministic (LLM only writes explanations)
            </h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {pipeline.map((a) => (
                <AgentCard key={a.agent_key} agent={a} />
              ))}
            </div>
          </section>
          <section aria-labelledby="objective-agents" className="space-y-3">
            <h2 id="objective-agents" className="text-base font-semibold text-ink">
              Objective III — LLM tool-calling agents (tools do all calculation)
            </h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {objective.map((a) => (
                <AgentCard key={a.agent_key} agent={a} />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
