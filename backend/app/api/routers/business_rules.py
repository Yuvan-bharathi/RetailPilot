"""Business rules (spec §5 GET/PUT /admin/business-rules, Super Admin only, D-48)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbSession, RequireSuperAdmin
from app.domain.schemas.common import DTO
from app.services.business_rule_service import BusinessRuleService, RuleSpec

router = APIRouter(tags=["admin"])

RuleValue = str | int | float | bool


class BusinessRuleDTO(DTO):
    key: str = Field(
        description="Rule key; keys inside basket / co_replenish are dotted, e.g. basket.min_support"
    )
    group: str
    label: str
    description: str
    kind: Literal["money", "decimal", "integer", "number", "boolean", "choice"]
    value: RuleValue
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None


class BusinessRuleUpdate(BaseModel):
    value: RuleValue


def _dto(spec: RuleSpec, value: Any) -> BusinessRuleDTO:
    return BusinessRuleDTO(
        key=spec.key,
        group=spec.group,
        label=spec.label,
        description=spec.description,
        kind=spec.kind,
        value=value,
        unit=spec.unit,
        min=spec.min,
        max=spec.max,
        choices=list(spec.choices) if spec.choices else None,
    )


@router.get("/admin/business-rules", response_model=list[BusinessRuleDTO])
async def list_business_rules(_admin: RequireSuperAdmin, session: DbSession) -> list[BusinessRuleDTO]:
    """The editable global business rules with their current values (spec §9)."""
    return [_dto(spec, value) for spec, value in await BusinessRuleService().list(session)]


@router.put("/admin/business-rules/{key}", response_model=BusinessRuleDTO)
async def update_business_rule(
    key: str, body: BusinessRuleUpdate, _admin: RequireSuperAdmin, session: DbSession
) -> BusinessRuleDTO:
    """Change one global rule (validated by type and range). Takes effect at the next nightly run."""
    spec, value = await BusinessRuleService().update(session, key, body.value)
    return _dto(spec, value)
