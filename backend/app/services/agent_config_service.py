"""Agent registry sync and the versioned on/off configuration (docs/09 §4, D-50).

- `agent_config` is append-only: every change is a new row with a new global `config_version`, the old and new
  value, who and why. The current value of an agent is its row with the highest version.
- A run reads the configuration ONCE at start (`snapshot`) and stores it on the run, so a toggle applies from the
  next run and never changes a run in progress.
- The global "All LLM agents" switch is the row with `agent_key` NULL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.agents.registry import AGENTS, BY_KEY, get_spec
from app.core.errors import ConflictError, ErrorDetail, NotFound, ValidationError
from app.domain.models.agents import AgentConfig, AgentDefinition
from app.domain.models.users import AppUser

LLM_SWITCH = "__llm__"  # key of the global switch in a snapshot dict
_LOCK_KEY = 50_050  # advisory lock serialising config versions


@dataclass(frozen=True)
class ConfigSnapshot:
    version: int
    enabled: dict[str, bool]  # own switch per agent
    llm_enabled: bool

    def is_on(self, agent_key: str) -> bool:
        """Effective: own switch AND (not an LLM agent OR the global LLM switch)."""
        spec = BY_KEY[agent_key]
        own = self.enabled.get(agent_key, True)
        return own and (spec.kind != "LLM" or self.llm_enabled)

    def as_json(self) -> dict[str, Any]:
        return {**self.enabled, LLM_SWITCH: self.llm_enabled}


def _definition_rows() -> list[dict[str, Any]]:
    return [
        {
            "agent_key": a.key,
            "name": a.name,
            "agent_group": a.group,
            "kind": a.kind,
            "pattern": a.pattern,
            "critical": a.critical,
            "depends_on": list(a.depends_on),
            "card_path": a.card_path,
            "sort_order": i,
        }
        for i, a in enumerate(AGENTS)
    ]


def sync_registry(session: Session) -> int:
    """Upsert `agent_definition` from the registry and create version 1 (all on) when no config exists.
    Idempotent; called by seed / seed_demo / the orchestrator."""
    rows = _definition_rows()
    stmt = pg_insert(AgentDefinition).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[AgentDefinition.agent_key],
            set_={c: stmt.excluded[c] for c in rows[0] if c != "agent_key"} | {"updated_at": func.now()},
        )
    )
    if session.scalar(select(func.count()).select_from(AgentConfig)) == 0:
        session.add(
            AgentConfig(
                agent_key=None,
                enabled=True,
                previous_enabled=None,
                config_version=1,
                reason="Initial configuration (all agents on)",
            )
        )
        for a in AGENTS:
            session.add(
                AgentConfig(
                    agent_key=a.key,
                    enabled=True,
                    previous_enabled=None,
                    config_version=1,
                    reason="Initial configuration (all agents on)",
                )
            )
    else:  # an agent registered later starts on, at the current version
        version = int(session.scalar(select(func.max(AgentConfig.config_version))) or 1)
        known = set(session.scalars(select(AgentConfig.agent_key).where(AgentConfig.agent_key.is_not(None))))
        for a in AGENTS:
            if a.key not in known:
                session.add(
                    AgentConfig(
                        agent_key=a.key,
                        enabled=True,
                        previous_enabled=None,
                        config_version=version,
                        reason="Agent registered",
                    )
                )
    session.flush()
    return len(rows)


_CURRENT_SQL = text(
    """
    SELECT DISTINCT ON (agent_key) agent_key, enabled, config_version
    FROM agent_config ORDER BY agent_key, config_version DESC, created_at DESC
    """
)


def _build_snapshot(rows: list[Any]) -> ConfigSnapshot:
    enabled: dict[str, bool] = {a.key: True for a in AGENTS}
    llm = True
    version = 0
    for key, on, v in rows:
        version = max(version, int(v))
        if key is None:
            llm = bool(on)
        elif key in enabled:
            enabled[key] = bool(on)
    return ConfigSnapshot(version=version, enabled=enabled, llm_enabled=llm)


def snapshot(session: Session) -> ConfigSnapshot:
    """The configuration a run starts with (sync, worker session)."""
    return _build_snapshot(list(session.execute(_CURRENT_SQL).all()))


async def snapshot_async(session: AsyncSession) -> ConfigSnapshot:
    return _build_snapshot(list((await session.execute(_CURRENT_SQL)).all()))


class AgentConfigService:
    async def _next_version(self, session: AsyncSession) -> int:
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        current = await session.scalar(select(func.max(AgentConfig.config_version)))
        return int(current or 0) + 1

    async def set_agent_enabled(
        self,
        session: AsyncSession,
        agent_key: str,
        enabled: bool,
        reason: str,
        user: AppUser,
        confirm_critical: bool = False,
    ) -> None:
        spec = get_spec(agent_key)
        if spec is None:
            raise NotFound(f"Unknown agent {agent_key}")
        reason = reason.strip()
        if len(reason) < 5:
            raise ValidationError(
                "A reason is required", details=[ErrorDetail(field="reason", message="required")]
            )
        if spec.critical and not enabled and not confirm_critical:
            raise ValidationError(
                "Turning off a critical agent pauses nightly replenishment and needs a second confirmation",
                details=[ErrorDetail(field="confirm_critical", message="must be true")],
            )
        snap = await snapshot_async(session)
        current = snap.enabled.get(agent_key, True)
        if current == enabled:
            raise ConflictError(f"{spec.name} is already {'on' if enabled else 'off'}")
        version = await self._next_version(session)
        session.add(
            AgentConfig(
                agent_key=agent_key,
                enabled=enabled,
                previous_enabled=current,
                config_version=version,
                updated_by=user.user_id,
                reason=reason,
            )
        )
        await session.commit()

    async def set_llm_enabled(self, session: AsyncSession, enabled: bool, reason: str, user: AppUser) -> None:
        reason = reason.strip()
        if len(reason) < 5:
            raise ValidationError(
                "A reason is required", details=[ErrorDetail(field="reason", message="required")]
            )
        snap = await snapshot_async(session)
        if snap.llm_enabled == enabled:
            raise ConflictError(f"All LLM agents are already {'on' if enabled else 'off'}")
        version = await self._next_version(session)
        session.add(
            AgentConfig(
                agent_key=None,
                enabled=enabled,
                previous_enabled=snap.llm_enabled,
                config_version=version,
                updated_by=user.user_id,
                reason=reason,
            )
        )
        await session.commit()
