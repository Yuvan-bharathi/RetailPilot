"""Ask RetailPilot (docs/08 pattern 1, D-50): any signed-in user; answers are scoped to the user's store."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.domain.schemas.agents import AskAnswerDTO, AskRequest, AskStatusDTO
from app.services.assistant_service import AssistantService

router = APIRouter(tags=["assistant"])

_assistant = AssistantService()


@router.get("/assistant/status", response_model=AskStatusDTO)
async def assistant_status(user: CurrentUser, session: DbSession) -> AskStatusDTO:
    return await _assistant.status(session, user)


@router.post("/assistant/ask", response_model=AskAnswerDTO)
async def ask(body: AskRequest, user: CurrentUser, session: DbSession) -> AskAnswerDTO:
    """Answer a question from recommendations, evidence, business rules and policies — with citations. The agent
    only reads; asking it to approve, submit or change anything is refused (409 when the agent is disabled)."""
    return await _assistant.ask(session, user, body.question)
