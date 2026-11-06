/**
 * "Run now" (docs/09 §3.6) and the on/off toggle (§4). Dry run is the default; Live needs a confirmation that
 * states the consequences and a written reason. Turning off a critical agent needs a second confirmation.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Play, Power, PowerOff, Rocket } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";

import { useApi } from "../../app/ApiContext";
import { useTriggerPreview } from "../../api/hooks";
import type { AgentSummaryDTO, RunMode, TriggerResultDTO } from "../../api/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { StatusBadge } from "../StatusBadge";
import { RunStatusBadge } from "./agentUi";

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}

function invalidateConsole(qc: ReturnType<typeof useQueryClient>) {
  for (const key of [
    "agents",
    "agent",
    "agent-runs",
    "pipeline-runs",
    "trigger-preview",
    "agent-decisions",
    "run-graph",
  ]) {
    void qc.invalidateQueries({ queryKey: [key] });
  }
}

export function RunNowPanel({ agent }: { agent: AgentSummaryDTO }) {
  const api = useApi();
  const qc = useQueryClient();
  const [mode, setMode] = useState<RunMode>("DRY_RUN");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [touched, setTouched] = useState(false);
  const [result, setResult] = useState<TriggerResultDTO | null>(null);
  const preview = useTriggerPreview(agent.agent_key, mode, agent.triggerable);
  const reasonId = useId();
  const groupName = useId();

  const trigger = useMutation({
    mutationFn: () =>
      api.triggerAgent(agent.agent_key, {
        mode,
        reason: mode === "LIVE" ? reason.trim() : reason.trim() || null,
        confirm: mode === "LIVE",
      }),
    onSuccess: (r) => {
      setResult(r);
      setConfirmOpen(false);
      setReason("");
      setUnderstood(false);
      setTouched(false);
      invalidateConsole(qc);
    },
  });

  if (!agent.triggerable) {
    return (
      <p className="text-sm text-ink-secondary">
        This agent is triggered by questions — use the{" "}
        <Link to="/ask" className="font-medium text-brand hover:underline">
          Ask RetailPilot
        </Link>{" "}
        page.
      </p>
    );
  }

  const p = preview.data;
  const blocked = p ? !p.allowed : true;
  const reasonMissing = reason.trim().length < 5;

  return (
    <div className="space-y-4">
      <fieldset>
        <legend className="text-xs font-medium text-ink-secondary">Mode</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {(
            [
              { value: "DRY_RUN", label: "Dry run (preview only)", icon: FlaskConical },
              { value: "LIVE", label: "Live (publishes)", icon: Rocket },
            ] as const
          ).map((o) => (
            <label
              key={o.value}
              className={`flex cursor-pointer items-center gap-2 rounded-button border px-3 py-2 text-sm ${
                mode === o.value ? "border-brand bg-brand-soft text-ink" : "border-border text-ink-secondary"
              }`}
            >
              <input
                type="radio"
                name={groupName}
                value={o.value}
                checked={mode === o.value}
                onChange={() => {
                  setMode(o.value);
                  setResult(null);
                }}
                className="accent-brand"
              />
              <o.icon aria-hidden="true" size={15} />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>

      {preview.isPending ? (
        <p className="text-sm text-ink-secondary">Checking dependencies…</p>
      ) : preview.isError ? (
        <p role="alert" className="text-sm text-danger">
          {errorText(preview.error)}
        </p>
      ) : p ? (
        <div className="space-y-2 text-sm">
          {p.upstream.length > 0 ? (
            <div>
              <span className="text-xs font-medium text-ink-secondary">Upstream inputs</span>
              <ul className="mt-1 flex flex-wrap gap-2">
                {p.upstream.map((u) => (
                  <li key={u.agent_key}>
                    <StatusBadge
                      tone={u.action === "REUSE" ? "success" : u.action === "RERUN" ? "attention" : "neutral"}
                      label={`${u.agent_key}: ${u.action === "REUSE" ? "fresh — reused" : u.action === "RERUN" ? "stale — re-run" : "disabled — skipped"}`}
                    />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div>
            <span className="text-xs font-medium text-ink-secondary">What happens</span>
            <ul className="mt-1 list-disc pl-5">
              {p.consequences.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
          {mode === "LIVE" ? (
            <p className="text-xs text-ink-secondary">
              Live triggers in the last hour: {p.live_triggers_last_hour} of {p.live_trigger_limit}
            </p>
          ) : null}
          {p.blocked_reason ? (
            <p role="status" className="rounded-input bg-warning-bg px-3 py-2 text-sm text-warning">
              Blocked: {p.blocked_reason}
            </p>
          ) : null}
        </div>
      ) : null}

      {mode === "DRY_RUN" ? (
        <div className="space-y-2">
          <label htmlFor={reasonId} className="text-xs font-medium text-ink-secondary">
            Note (optional)
          </label>
          <input
            id={reasonId}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="h-9 w-full rounded-input border border-border px-2 text-sm"
          />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          icon={<Play size={15} />}
          disabled={blocked || trigger.isPending}
          onClick={() => (mode === "LIVE" ? setConfirmOpen(true) : trigger.mutate())}
        >
          {trigger.isPending ? "Starting…" : mode === "LIVE" ? "Run live…" : "Start dry run"}
        </Button>
        {trigger.isError ? (
          <span role="alert" className="text-sm text-danger">
            {errorText(trigger.error)}
          </span>
        ) : null}
        {result ? (
          <span role="status" className="flex items-center gap-2 text-sm">
            <RunStatusBadge status={result.status} />
            {result.message} —{" "}
            <Link to={`/agents/logs/${result.run_id}`} className="font-medium text-brand hover:underline">
              open trace
            </Link>
          </span>
        ) : null}
      </div>

      <Modal
        open={confirmOpen}
        title={`Run ${agent.name} live?`}
        description="A live run publishes like a nightly stage."
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setTouched(true);
                if (reasonMissing || !understood) return;
                trigger.mutate();
              }}
              disabled={trigger.isPending}
            >
              Run live
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <p className="text-xs font-medium text-ink-secondary">Consequences</p>
            <ul className="list-disc pl-5">
              {(p?.consequences ?? []).map((c) => (
                <li key={c}>{c}</li>
              ))}
              {p && p.recommendations_to_supersede > 0 ? (
                <li>{p.recommendations_to_supersede} pending recommendations will be superseded</li>
              ) : null}
            </ul>
          </div>
          <div>
            <label htmlFor={`${reasonId}-live`} className="text-sm font-medium">
              Reason <span className="text-danger">*</span>
            </label>
            <textarea
              id={`${reasonId}-live`}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-invalid={touched && reasonMissing}
              className="mt-1 w-full rounded-input border border-border p-2 text-sm"
            />
            {touched && reasonMissing ? <p className="text-xs text-danger">Enter a reason (5+ characters).</p> : null}
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={understood}
              onChange={(e) => setUnderstood(e.target.checked)}
              className="mt-0.5 accent-brand"
            />
            I understand these consequences.
          </label>
          {touched && !understood ? <p className="text-xs text-danger">Confirm the consequences first.</p> : null}
          {trigger.isError ? (
            <p role="alert" className="text-sm text-danger">
              {errorText(trigger.error)}
            </p>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}

/** On/off toggle: reason required; critical agents need a second confirmation (pauses replenishment). */
export function ToggleAgentButton({ agent }: { agent: AgentSummaryDTO }) {
  const api = useApi();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [second, setSecond] = useState(false);
  const [touched, setTouched] = useState(false);
  const turningOff = agent.enabled;
  const needsSecond = turningOff && agent.critical;
  const reasonId = useId();

  const mutation = useMutation({
    mutationFn: () =>
      api.toggleAgent(agent.agent_key, { enabled: !agent.enabled, reason: reason.trim(), confirm_critical: second }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      setSecond(false);
      setTouched(false);
      invalidateConsole(qc);
    },
  });
  const missing = reason.trim().length < 5;

  return (
    <>
      <Button
        size="sm"
        variant={turningOff ? "destructive" : "secondary"}
        icon={turningOff ? <PowerOff size={14} /> : <Power size={14} />}
        onClick={() => setOpen(true)}
        aria-label={`${turningOff ? "Turn off" : "Turn on"} ${agent.name}`}
      >
        {turningOff ? "Turn off" : "Turn on"}
      </Button>
      <Modal
        open={open}
        title={`${turningOff ? "Turn off" : "Turn on"} ${agent.name}?`}
        description="Takes effect from the next run; a run in progress keeps the configuration it started with."
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={turningOff ? "destructive" : "primary"}
              disabled={mutation.isPending}
              onClick={() => {
                setTouched(true);
                if (missing || (needsSecond && !second)) return;
                mutation.mutate();
              }}
            >
              {turningOff ? "Turn off" : "Turn on"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {turningOff ? (
            <p>
              <span className="text-xs font-medium text-ink-secondary">Effect: </span>
              {agent.critical
                ? "Nightly replenishment is paused: no new recommendations or POs; users keep the last results."
                : "See the agent card for what changes while it is off."}
            </p>
          ) : null}
          <div>
            <label htmlFor={reasonId} className="text-sm font-medium">
              Reason <span className="text-danger">*</span>
            </label>
            <textarea
              id={reasonId}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-invalid={touched && missing}
              className="mt-1 w-full rounded-input border border-border p-2 text-sm"
            />
            {touched && missing ? <p className="text-xs text-danger">Enter a reason (5+ characters).</p> : null}
          </div>
          {needsSecond ? (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={second}
                onChange={(e) => setSecond(e.target.checked)}
                className="mt-0.5 accent-brand"
              />
              I confirm that nightly replenishment will be paused.
            </label>
          ) : null}
          {touched && needsSecond && !second ? (
            <p className="text-xs text-danger">Second confirmation required.</p>
          ) : null}
          {mutation.isError ? (
            <p role="alert" className="text-sm text-danger">
              {errorText(mutation.error)}
            </p>
          ) : null}
        </div>
      </Modal>
    </>
  );
}
