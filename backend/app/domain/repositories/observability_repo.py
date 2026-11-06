"""Observability repository: AgentRunLogger for tracking agent runs, tool calls, and LLM usage (SD-01, SD-02)."""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.models.observability import AgentRun, DecisionEvidence, LLMUsage, ToolCall

#: per-run stats stored when a run finishes (D-54); same definition as migration 0005's backfill
RUN_STATS_SQL = text(
    """
    UPDATE agent_run r SET
        duration_ms = CASE WHEN r.ended_at IS NULL THEN NULL
                           ELSE (extract(epoch FROM r.ended_at - r.started_at) * 1000)::int END,
        tool_calls_count = (SELECT count(*) FROM tool_call t WHERE t.run_id = r.run_id),
        llm_calls_count = (SELECT count(*) FROM llm_usage u WHERE u.run_id = r.run_id),
        tokens = (SELECT coalesce(sum(u.input_tokens + u.output_tokens), 0) FROM llm_usage u WHERE u.run_id = r.run_id),
        est_cost_usd = (SELECT coalesce(sum(u.est_cost), 0) FROM llm_usage u WHERE u.run_id = r.run_id),
        decisions_count = CASE WHEN r.parent_run_id IS NULL
            THEN (SELECT count(*) FROM agent_decision d WHERE d.run_id = r.run_id)
            ELSE (SELECT count(*) FROM agent_decision d
                  WHERE d.run_id = r.parent_run_id AND d.agent_key = r.agent_key) END
    WHERE r.run_id = :run
    """
)


class AgentRunLogger:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start_run(
        self,
        agent_name: str,
        parent_run_id: UUID | None,
        input_ref: dict[str, Any],
        run_id: UUID | None = None,
        run_date: date | None = None,
        **fields: Any,
    ) -> UUID:
        """`fields`: agent console columns (agent_key, trigger_type, mode, config_version, config_snapshot,
        triggered_by, reason) — D-50."""
        if run_id is None:
            run_id = uuid.uuid4()
        now = datetime.now(UTC)
        if run_date is None and "run_date" in input_ref:
            rd_val = input_ref["run_date"]
            if isinstance(rd_val, str):
                with contextlib.suppress(ValueError):
                    run_date = date.fromisoformat(rd_val)
            elif isinstance(rd_val, date):
                run_date = rd_val

        run = AgentRun(
            run_id=run_id,
            parent_run_id=parent_run_id,
            agent_name=agent_name,
            run_date=run_date,
            status="RUNNING",
            started_at=now,
            input_ref=input_ref,
            output_summary=None,
            **fields,
        )
        self.session.add(run)
        self.session.flush()
        return run_id

    def log_tool_call(
        self,
        run_id: UUID,
        tool_name: str,
        args: dict[str, Any],
        result_summary: str | dict[str, Any],
        duration_ms: int,
        status: str = "OK",
    ) -> None:
        summary_str = (
            json.dumps(result_summary) if isinstance(result_summary, (dict, list)) else str(result_summary)
        )
        call = ToolCall(
            call_id=uuid.uuid4(),
            run_id=run_id,
            tool_name=tool_name,
            duration_ms=duration_ms,
            status=status,
            args=args,
            result_summary=summary_str,
        )
        self.session.add(call)
        self.session.flush()

    def log_evidence(
        self,
        run_id: UUID,
        rec_id: UUID | None,
        data: dict[str, Any],
        validation_result: str,
    ) -> None:
        evidence = DecisionEvidence(
            evidence_id=uuid.uuid4(),
            run_id=run_id,
            rec_id=rec_id,
            data=data,
            validation_result=validation_result,
        )
        self.session.add(evidence)
        self.session.flush()

    def log_llm_usage(
        self,
        run_id: UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        est_cost: Decimal = Decimal(0),
        latency_ms: int | None = None,
    ) -> None:
        # column names per the model (input_tokens / output_tokens / est_cost); the earlier keywords
        # prompt_tokens / completion_tokens raised TypeError, which the caller swallowed — nothing was logged
        usage = LLMUsage(
            usage_id=uuid.uuid4(),
            run_id=run_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            est_cost=est_cost,
            latency_ms=latency_ms,
        )
        self.session.add(usage)
        self.session.flush()

    def finish_run(
        self,
        run_id: UUID,
        status: str,
        output_summary: dict[str, Any] | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        retries: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        run = self.session.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).one_or_none()
        if run:
            run.status = status
            run.ended_at = now
            if output_summary is not None:
                run.output_summary = (
                    json.dumps(output_summary) if isinstance(output_summary, dict) else str(output_summary)
                )
            run.error = error
            if stop_reason is not None:
                run.stop_reason = stop_reason
            if retries is not None:
                run.retries = retries
            self.session.flush()
            self.store_stats(run_id)

    def store_stats(self, run_id: UUID | None) -> None:
        """Write the run's stats once (D-54); also called again after a stage's decisions are recorded."""
        if run_id is None:
            return
        self.session.execute(RUN_STATS_SQL, {"run": run_id})
        for obj in list(self.session.identity_map.values()):
            if isinstance(obj, AgentRun) and obj.run_id == run_id:
                self.session.expire(obj)
