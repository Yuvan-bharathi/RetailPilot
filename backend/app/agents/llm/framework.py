"""Tool-loop agent framework (docs/08 §4, D-50): model instructions, an explicit tool allow-list, structured output,
stopping conditions and logging. Tools do ALL calculation; the model only decides which approved tool to call and
how to compose results.

Loop:
1. system instructions (versioned prompt file) + the user/task message;
2. the model calls allowed tools; each call is validated (Pydantic args), executed with the caller's scope, logged
   (AgentRunLogger.tool_call) and its compact JSON result returned to the model as DATA;
3. the model ends by calling the agent's submit tool; its arguments are validated against the output model —
   invalid → one corrective retry → fail safe (`stop_reason="invalid_output"`, no output);
4. stops early on: max tool calls, token budget, timeout, model error, a reply with no tool call (after one nudge).
A tool that is not on the allow-list (e.g. "approve_purchase_order") is refused and logged with status ERROR —
consequential operations are not tools at all (docs/08 §5).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.agents.llm.chat import ChatLLM
from app.domain.repositories.observability_repo import AgentRunLogger
from app.services.llm_client import LLMError

ToolKind = Literal["READ", "DRAFT_WRITE"]
MAX_RESULT_CHARS = 6_000


class ToolError(Exception):
    """A tool refused or failed in a defined way; the message goes back to the model as the tool result."""


@dataclass
class ToolContext:
    """The caller's scope (rule 10) and per-run scratchpad. Tools never widen access beyond this."""

    session: Session
    role: Literal["SUPER_ADMIN", "STORE_SUPERVISOR"]
    store_id: UUID | None  # supervisor's own store; None for Super Admin
    run_id: UUID  # agent run being logged (drafts and decisions reference it)
    scope_run_id: UUID | None = None  # nightly run whose outputs are read (latest by default)
    mode: Literal["LIVE", "DRY_RUN"] = "LIVE"
    user_id: UUID | None = None
    #: ids every tool returned in this run — citations and drafts may only reference these
    seen_ids: set[str] = field(default_factory=set)
    #: numbers every tool returned — answers may only state these (groundedness, rule 11)
    seen_numbers: set[Decimal] = field(default_factory=set)
    #: allowed quantities per rec_id from get_transfer_options / get_recommendation
    allowed_qty: dict[str, set[int]] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def root_run_id(self) -> UUID:
        """Root run (nightly, manual trigger or question) that decisions and drafts belong to."""
        root = self.cache.get("root_run_id")
        return root if isinstance(root, UUID) else self.run_id

    @property
    def is_admin(self) -> bool:
        return self.role == "SUPER_ADMIN"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    kind: ToolKind
    fn: Callable[[ToolContext, Any], dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        params = self.args_model.model_json_schema()
        params.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 6
    max_tokens: int = 12_000
    timeout_s: float = 45.0
    max_turns: int = 10


@dataclass
class ToolTrace:
    name: str
    args: dict[str, Any]
    status: Literal["OK", "WARN", "ERROR"]
    result: dict[str, Any] | str
    duration_ms: int


@dataclass
class LoopResult[T: BaseModel]:
    output: T | None
    stop_reason: str
    tools: list[ToolTrace] = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost: Decimal = Decimal(0)
    latency_ms: int = 0
    error: str | None = None

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def tool_sequence(self) -> list[str]:
        return [t.name for t in self.tools]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def compact(result: dict[str, Any]) -> str:
    text = json.dumps(_jsonable(result), separators=(",", ":"), ensure_ascii=False)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '…"(truncated)"'


def remember(ctx: ToolContext, value: Any) -> None:
    """Record ids and numbers a tool returned (for citation and groundedness checks)."""
    from app.services.explanation_service import fact_numbers

    def ids(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                if (k.endswith("_id") or k == "id") and isinstance(x, str | UUID):
                    ctx.seen_ids.add(str(x))
                ids(x)
        elif isinstance(v, list):
            for x in v:
                ids(x)

    jv = _jsonable(value)
    ids(jv)
    ctx.seen_numbers |= fact_numbers(jv)


class ToolLoopAgent[T: BaseModel]:
    def __init__(
        self,
        *,
        agent_key: str,
        system_prompt: str,
        tools: list[ToolSpec],
        submit_name: str,
        submit_description: str,
        output_model: type[T],
        limits: Limits,
        llm: ChatLLM,
        logger: AgentRunLogger | None,
    ) -> None:
        self.agent_key = agent_key
        self.system_prompt = system_prompt
        self.tools = {t.name: t for t in tools}
        self.submit_name = submit_name
        self.submit_description = submit_description
        self.output_model = output_model
        self.limits = limits
        self.llm = llm
        self.logger = logger

    def _schemas(self) -> list[dict[str, Any]]:
        out_schema = self.output_model.model_json_schema()
        out_schema.pop("title", None)
        submit = {
            "type": "function",
            "function": {
                "name": self.submit_name,
                "description": self.submit_description,
                "parameters": out_schema,
            },
        }
        return [t.schema() for t in self.tools.values()] + [submit]

    def _log_tool(self, ctx: ToolContext, trace: ToolTrace) -> None:
        if self.logger is None:
            return
        summary = trace.result if isinstance(trace.result, str) else compact(trace.result)
        self.logger.log_tool_call(
            run_id=ctx.run_id,
            tool_name=trace.name,
            args=_jsonable(trace.args),
            result_summary=summary[:2_000],
            duration_ms=trace.duration_ms,
            status=trace.status,
        )

    def run(self, ctx: ToolContext, task: str) -> LoopResult[T]:
        res: LoopResult[T] = LoopResult(output=None, stop_reason="")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]
        schemas = self._schemas()
        deadline = time.monotonic() + self.limits.timeout_s
        t_start = time.monotonic()
        tool_calls = 0
        over_limit = 0
        invalid_outputs = 0
        nudged = False

        def done(reason: str, error: str | None = None) -> LoopResult[T]:
            res.stop_reason = reason
            res.error = error
            res.latency_ms = int((time.monotonic() - t_start) * 1000)
            return res

        for _turn in range(self.limits.max_turns):
            if time.monotonic() > deadline:
                return done("timeout")
            if res.tokens >= self.limits.max_tokens:
                return done("token_budget")
            try:
                turn = self.llm.chat(messages, schemas)
            except LLMError as exc:
                return done("model_error", str(exc)[:300])
            res.llm_calls += 1
            res.input_tokens += turn.input_tokens
            res.output_tokens += turn.output_tokens
            res.est_cost += turn.est_cost
            if self.logger is not None:
                self.logger.log_llm_usage(
                    run_id=ctx.run_id,
                    provider=self.llm.provider,
                    model=turn.model,
                    input_tokens=turn.input_tokens,
                    output_tokens=turn.output_tokens,
                    est_cost=turn.est_cost,
                    latency_ms=turn.latency_ms,
                )
            if not turn.tool_calls:
                if nudged:
                    return done("no_submit", "The model answered without calling the submit tool")
                nudged = True
                messages.append({"role": "assistant", "content": turn.content or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Finish by calling {self.submit_name} with the structured result.",
                    }
                )
                continue
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": c.arguments},
                        }
                        for c in turn.tool_calls
                    ],
                }
            )
            for call in turn.tool_calls:
                t0 = time.monotonic()
                try:
                    raw_args = json.loads(call.arguments or "{}")
                    if not isinstance(raw_args, dict):
                        raise ValueError("arguments must be a JSON object")
                except ValueError as exc:
                    raw_args = {}
                    content = f"ERROR: arguments are not valid JSON ({exc})"
                    self._append_tool(messages, call.id, content)
                    self._record(ctx, res, call.name, raw_args, "ERROR", content, t0)
                    continue

                if call.name == self.submit_name:
                    try:
                        output = self.output_model.model_validate(raw_args)
                    except ValidationError as exc:
                        invalid_outputs += 1
                        msg = f"ERROR: invalid output — {exc.errors(include_url=False)[:3]}"
                        self._append_tool(messages, call.id, msg)
                        self._record(ctx, res, call.name, raw_args, "ERROR", msg, t0)
                        if invalid_outputs >= 2:
                            return done("invalid_output", "Output failed validation twice")
                        continue
                    self._record(ctx, res, call.name, raw_args, "OK", "accepted", t0)
                    res.output = output
                    return done("submitted")

                spec = self.tools.get(call.name)
                if spec is None:
                    msg = f"ERROR: tool '{call.name}' is not allowed for this agent. Allowed: {', '.join(self.tools)}"
                    self._append_tool(messages, call.id, msg)
                    self._record(ctx, res, call.name, raw_args, "ERROR", msg, t0)
                    continue
                if tool_calls >= self.limits.max_tool_calls:
                    over_limit += 1
                    msg = f"ERROR: tool-call limit ({self.limits.max_tool_calls}) reached — call {self.submit_name} now"
                    self._append_tool(messages, call.id, msg)
                    self._record(ctx, res, call.name, raw_args, "WARN", msg, t0)
                    continue
                tool_calls += 1
                try:
                    args = spec.args_model.model_validate(raw_args)
                    result = spec.fn(ctx, args)
                    remember(ctx, result)
                    self._append_tool(messages, call.id, compact(result))
                    self._record(ctx, res, call.name, raw_args, "OK", result, t0)
                except ValidationError as exc:
                    msg = f"ERROR: invalid arguments — {exc.errors(include_url=False)[:3]}"
                    self._append_tool(messages, call.id, msg)
                    self._record(ctx, res, call.name, raw_args, "ERROR", msg, t0)
                except ToolError as exc:
                    msg = f"ERROR: {exc}"
                    self._append_tool(messages, call.id, msg)
                    self._record(ctx, res, call.name, raw_args, "ERROR", msg, t0)
                except Exception as exc:  # a failing tool must not crash the agent: defined outcome
                    msg = f"ERROR: tool failed ({type(exc).__name__})"
                    self._append_tool(messages, call.id, msg)
                    self._record(ctx, res, call.name, raw_args, "ERROR", msg, t0)
            if over_limit >= 2:  # warned once, the model still calls tools: stop
                return done("max_tool_calls")
        return done("max_turns")

    @staticmethod
    def _append_tool(messages: list[dict[str, Any]], call_id: str, content: str) -> None:
        messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

    def _record(
        self,
        ctx: ToolContext,
        res: LoopResult[T],
        name: str,
        args: dict[str, Any],
        status: Literal["OK", "WARN", "ERROR"],
        result: dict[str, Any] | str,
        t0: float,
    ) -> None:
        trace = ToolTrace(name, args, status, result, int((time.monotonic() - t0) * 1000))
        res.tools.append(trace)
        self._log_tool(ctx, trace)


def new_run_id() -> UUID:
    return uuid.uuid4()
