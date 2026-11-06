"""Ask RetailPilot service (docs/08 pattern 1, D-50). Each question is an ON_DEMAND agent run (logged with its tool
calls and LLM usage) and one decision row (ANSWER_GIVEN / NOT_FOUND / REQUEST_REFUSED). Scoped to the asking user."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.domain.models.users import AppUser
from app.domain.schemas.agents import AskAnswerDTO, AskStatusDTO, CitationDTO
from app.services.agent_config_service import snapshot, snapshot_async

EXAMPLES = [
    "Why are we ordering butter?",
    "What did Store A transfer this week?",
    "What is the approval threshold for purchase orders?",
    "When must a transfer be received?",
]


def _ask_sync(user_id: uuid.UUID, role: str, store_id: uuid.UUID | None, question: str) -> AskAnswerDTO:
    from app.agents.llm.agents import answer_question, make_chat_llm
    from app.agents.llm.framework import ToolContext
    from app.core.db import get_sync_session_factory
    from app.domain.repositories.observability_repo import AgentRunLogger
    from app.services.agent_decision_service import record_decision

    t0 = time.monotonic()
    with get_sync_session_factory()() as session:
        snap = snapshot(session)
        if not snap.is_on("ask_retailpilot"):
            raise ConflictError("Ask RetailPilot is disabled")
        logger = AgentRunLogger(session)
        run_id = logger.start_run(
            agent_name="AskRetailPilot",
            parent_run_id=None,
            input_ref={"question": question[:500], "role": role},
            agent_key="ask_retailpilot",
            trigger_type="ON_DEMAND",
            triggered_by=user_id,
            config_version=snap.version,
        )
        ctx = ToolContext(session=session, role=role, store_id=store_id, run_id=run_id, user_id=user_id)  # type: ignore[arg-type]
        res = answer_question(ctx, question, make_chat_llm(), logger)
        latency = int((time.monotonic() - t0) * 1000)
        record_decision(
            session,
            run_id=run_id,
            agent_key="ask_retailpilot",
            decision_type=res.decision_type,
            summary=f"Q: {question[:200]} → {res.answer.answer[:250]}",
            store_id=store_id,
            evidence_ref={
                "citations": [c.model_dump() for c in res.answer.citations],
                "mode": res.mode,
                "grounded": res.grounded,
            },
        )
        logger.finish_run(
            run_id,
            status="SUCCESS",
            output_summary={
                "found": res.answer.found,
                "refused": res.answer.refused,
                "mode": res.mode,
                "citations": len(res.answer.citations),
            },
            stop_reason=res.loop.stop_reason
            if res.loop
            else ("refused" if res.answer.refused else "retrieval only"),
        )
        session.commit()
        return AskAnswerDTO(
            answer=res.answer.answer,
            found=res.answer.found,
            refused=res.answer.refused,
            citations=[CitationDTO(**c.model_dump()) for c in res.answer.citations],
            run_id=run_id,
            latency_ms=latency,
            mode=res.mode,
        )


class AssistantService:
    async def status(self, session: AsyncSession, user: AppUser) -> AskStatusDTO:
        snap = await snapshot_async(session)
        return AskStatusDTO(enabled=snap.is_on("ask_retailpilot"), examples=EXAMPLES)

    async def ask(self, session: AsyncSession, user: AppUser, question: str) -> AskAnswerDTO:
        snap = await snapshot_async(session)
        if not snap.is_on("ask_retailpilot"):
            raise ConflictError("Ask RetailPilot is disabled")
        _ = datetime.now(UTC)
        return await run_in_threadpool(_ask_sync, user.user_id, user.role, user.store_id, question)
