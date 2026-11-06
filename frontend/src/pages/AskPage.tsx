/** Ask RetailPilot (docs/08 pattern 1): questions answered from records and policies, always with sources. */
import { useMutation } from "@tanstack/react-query";
import { BookOpen, FileText, MessageSquareText, Send, ShieldOff } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";

import { useApi } from "../app/ApiContext";
import { useAssistantStatus } from "../api/hooks";
import type { AskAnswerDTO, CitationDTO } from "../api/types";
import { Button } from "../components/Button";
import { ErrorState, SkeletonLine } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";

const SOURCE_LABEL: Record<CitationDTO["source_type"], string> = {
  RECOMMENDATION: "Recommendation",
  EVIDENCE: "Evidence",
  BUSINESS_RULE: "Business rule",
  POLICY: "Policy",
  TRANSFER: "Transfer",
  INVENTORY: "Inventory",
};

function CitationLink({ c }: { c: CitationDTO }) {
  const body = (
    <>
      {c.source_type === "POLICY" ? (
        <BookOpen aria-hidden="true" size={13} />
      ) : (
        <FileText aria-hidden="true" size={13} />
      )}
      <span className="text-ink-secondary">{SOURCE_LABEL[c.source_type]}:</span> {c.label}
    </>
  );
  return c.source_type === "RECOMMENDATION" || c.source_type === "EVIDENCE" ? (
    <Link to={`/recommendations/${c.source_id}`} className="inline-flex items-center gap-1 text-brand hover:underline">
      {body}
    </Link>
  ) : (
    <span className="inline-flex items-center gap-1">{body}</span>
  );
}

interface Turn {
  question: string;
  answer: AskAnswerDTO | null;
  error: string | null;
}

export function AskPage() {
  const api = useApi();
  const status = useAssistantStatus();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const id = useId();
  const ask = useMutation({
    mutationFn: (q: string) => api.ask(q),
    onSuccess: (answer, q) => setTurns((t) => [{ question: q, answer, error: null }, ...t]),
    onError: (e: Error, q) => setTurns((t) => [{ question: q, answer: null, error: e.message }, ...t]),
  });
  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 3 || ask.isPending) return;
    ask.mutate(text);
    setQuestion("");
  };

  if (status.isError) return <ErrorState message={status.error.message} onRetry={() => void status.refetch()} />;
  if (status.isPending)
    return (
      <div aria-label="Loading" className="space-y-2">
        <SkeletonLine />
      </div>
    );

  if (!status.data.enabled) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-card border border-border bg-surface px-6 py-12 text-center shadow-card">
        <ShieldOff aria-hidden="true" size={28} className="text-ink-secondary" />
        <p className="font-semibold text-ink">Agent disabled</p>
        <p className="max-w-md text-sm text-ink-secondary">
          Ask RetailPilot is switched off by the Super Admin. Recommendations and their evidence are still available on
          the recommendation screens.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="rounded-card border border-border bg-surface p-4 shadow-card">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
          className="space-y-3"
        >
          <label htmlFor={id} className="flex items-center gap-2 text-sm font-semibold text-ink">
            <MessageSquareText aria-hidden="true" size={16} /> Ask a question about recommendations, transfers, rules or
            policies
          </label>
          <div className="flex gap-2">
            <input
              id={id}
              value={question}
              maxLength={500}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Why are we ordering butter?"
              className="h-10 min-w-0 flex-1 rounded-input border border-border px-3 text-sm"
            />
            <Button type="submit" icon={<Send size={15} />} disabled={question.trim().length < 3 || ask.isPending}>
              {ask.isPending ? "Thinking…" : "Ask"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {status.data.examples.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => submit(ex)}
                className="rounded-full border border-border px-3 py-1 text-xs text-ink-secondary hover:bg-elevated hover:text-ink"
              >
                {ex}
              </button>
            ))}
          </div>
          <p className="text-xs text-ink-secondary">
            Answers use only the data you can see and always list their sources. The assistant cannot approve, submit or
            change anything.
          </p>
        </form>
      </div>
      <ol aria-label="Answers" aria-live="polite" className="space-y-4">
        {turns.map((t, i) => (
          <li key={turns.length - i} className="rounded-card border border-border bg-surface p-4 shadow-card">
            <p className="text-sm font-semibold text-ink">{t.question}</p>
            {t.error ? (
              <p role="alert" className="mt-2 text-sm text-danger">
                {t.error}
              </p>
            ) : t.answer ? (
              <div className="mt-2 space-y-2">
                <div className="flex flex-wrap gap-2">
                  {t.answer.refused ? (
                    <StatusBadge tone="warning" label="Not allowed — read-only assistant" />
                  ) : t.answer.found ? (
                    <StatusBadge tone="success" label="Answered from sources" />
                  ) : (
                    <StatusBadge tone="neutral" label="Not found" />
                  )}
                  {t.answer.mode === "RETRIEVAL_ONLY" ? (
                    <StatusBadge tone="info" label="Sources only (LLM off)" />
                  ) : null}
                </div>
                <p className="whitespace-pre-line text-sm text-ink">{t.answer.answer}</p>
                {t.answer.citations.length ? (
                  <div>
                    <p className="text-xs font-medium text-ink-secondary">Sources</p>
                    <ul className="mt-1 space-y-1 text-sm">
                      {t.answer.citations.map((c) => (
                        <li key={`${c.source_type}-${c.source_id}`}>
                          <CitationLink c={c} />
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
