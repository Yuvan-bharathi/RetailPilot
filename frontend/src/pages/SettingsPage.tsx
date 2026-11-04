/**
 * Settings (D-48). Super Admin: the business rules of spec §9 from GET /admin/business-rules, edited one at a time
 * with PUT (validated by the API; changes apply at the next nightly run). Store Supervisor: their profile (read only).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../api/client";
import { useBusinessRules } from "../api/hooks";
import type { BusinessRuleDTO } from "../api/types";
import { useApi } from "../app/ApiContext";
import { useAuth } from "../app/AuthContext";
import { Button } from "../components/Button";
import { EmptyState, ErrorState, SkeletonLine } from "../components/StateViews";

type Value = BusinessRuleDTO["value"];

function display(rule: BusinessRuleDTO): string {
  if (rule.kind === "boolean") return rule.value ? "Yes" : "No";
  if (rule.kind === "money") return `₹${rule.value}`;
  return `${String(rule.value)}${rule.unit && rule.kind !== "choice" ? ` ${rule.unit}` : ""}`;
}

function RuleRow({ rule }: { rule: BusinessRuleDTO }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string>(String(rule.value));
  const [editing, setEditing] = useState(false);
  const save = useMutation({
    mutationFn: (value: Value) => api.updateBusinessRule(rule.key, value),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["business-rules"] });
    },
  });
  const inputId = `rule-${rule.key}`;
  const parsed = (): Value => {
    if (rule.kind === "boolean") return draft === "true";
    if (rule.kind === "choice" || rule.kind === "money" || rule.kind === "decimal") return draft;
    return Number(draft);
  };
  const error = save.error instanceof ApiError ? save.error.message : save.error ? "Could not save" : null;

  return (
    <li className="flex flex-col gap-2 border-t border-divider py-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 sm:w-1/2">
        <label htmlFor={inputId} className="font-medium text-ink">
          {rule.label}
        </label>
        <p className="text-xs text-ink-secondary">{rule.description}</p>
      </div>
      {editing ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(parsed());
          }}
        >
          {rule.kind === "boolean" || rule.kind === "choice" ? (
            <select
              id={inputId}
              className="h-9 rounded-input border border-border bg-surface px-2 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            >
              {(rule.kind === "boolean" ? ["true", "false"] : (rule.choices ?? [])).map((c) => (
                <option key={c} value={c}>
                  {rule.kind === "boolean" ? (c === "true" ? "Yes" : "No") : c}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={inputId}
              className="tabular h-9 w-36 rounded-input border border-border bg-surface px-2 text-sm"
              inputMode="decimal"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-describedby={error ? `${inputId}-error` : undefined}
            />
          )}
          {rule.unit && rule.kind !== "money" ? <span className="text-xs text-ink-secondary">{rule.unit}</span> : null}
          <Button type="submit" size="sm" disabled={save.isPending}>
            Save
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => {
              setDraft(String(rule.value));
              setEditing(false);
              save.reset();
            }}
          >
            Cancel
          </Button>
          {error ? (
            <p id={`${inputId}-error`} role="alert" className="w-full text-xs text-danger">
              {error}
            </p>
          ) : null}
        </form>
      ) : (
        <div className="flex items-center gap-3">
          <span id={inputId} className="tabular text-sm font-semibold text-ink">
            {display(rule)}
          </span>
          <Button size="sm" variant="secondary" aria-label={`Change ${rule.label}`} onClick={() => setEditing(true)}>
            Change
          </Button>
        </div>
      )}
    </li>
  );
}

function BusinessRules() {
  const rules = useBusinessRules();
  if (rules.isPending)
    return (
      <div className="space-y-3">
        <SkeletonLine />
        <SkeletonLine width="80%" />
      </div>
    );
  if (rules.error) return <ErrorState message={rules.error.message} onRetry={() => void rules.refetch()} />;
  if (!rules.data?.length) return <EmptyState title="No business rules configured" />;
  const groups = [...new Set(rules.data.map((r) => r.group))];
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section
          key={group}
          aria-label={group}
          className="rounded-card border border-border bg-surface p-5 shadow-card"
        >
          <h2 className="pb-1 text-sm font-semibold text-ink">{group}</h2>
          <ul>
            {rules.data
              .filter((r) => r.group === group)
              .map((r) => (
                <RuleRow key={r.key} rule={r} />
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "SUPER_ADMIN";
  return (
    <div className="space-y-6">
      <header>
        {isAdmin ? <h2 className="text-lg font-semibold text-ink">Business rules</h2> : null}
        <p className="mt-1 text-sm text-ink-secondary">
          {isAdmin
            ? "Parameters of the nightly planning run (spec §9). Changes apply from the next run."
            : "Your account. Business rules are managed by the Super Admin."}
        </p>
      </header>
      <section aria-label="Account" className="rounded-card border border-border bg-surface p-5 shadow-card">
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-ink-secondary">Name</dt>
            <dd className="font-medium text-ink">{user?.name ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-secondary">Role</dt>
            <dd className="font-medium text-ink">{isAdmin ? "Super Admin" : "Store Supervisor"}</dd>
          </div>
          <div>
            <dt className="text-ink-secondary">Store</dt>
            <dd className="font-medium text-ink">{user?.store?.name ?? "All stores"}</dd>
          </div>
        </dl>
      </section>
      {isAdmin ? <BusinessRules /> : null}
    </div>
  );
}
