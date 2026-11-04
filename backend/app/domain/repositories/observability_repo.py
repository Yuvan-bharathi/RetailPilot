"""Observability repository: AgentRunLogger for tracking agent runs, tool calls, and LLM usage (SD-01, SD-02)."""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.observability import AgentRun, DecisionEvidence, LLMUsage, ToolCall


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
    ) -> UUID:
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
            json.dumps(result_summary)
            if isinstance(result_summary, (dict, list))
            else str(result_summary)
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
    ) -> None:
        usage = LLMUsage(
            usage_id=uuid.uuid4(),
            run_id=run_id,
            provider=provider,
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        )
        self.session.add(usage)
        self.session.flush()

    def finish_run(
        self,
        run_id: UUID,
        status: str,
        output_summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        run = self.session.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).one_or_none()
        if run:
            run.status = status
            run.ended_at = now
            if output_summary is not None:
                run.output_summary = (
                    json.dumps(output_summary)
                    if isinstance(output_summary, dict)
                    else str(output_summary)
                )
            run.error = error
            self.session.flush()
