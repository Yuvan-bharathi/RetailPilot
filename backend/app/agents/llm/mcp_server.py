"""`retailpilot-tools` — internal MCP server (docs/08 §5, D-50).

Exposes the approved agent tools (app/agents/llm/tools.py) over the Model Context Protocol, stdio transport
(newline-delimited JSON-RPC 2.0): `initialize`, `ping`, `tools/list`, `tools/call`. Implemented without the MCP SDK
(no new dependency); protocol versions 2025-06-18 / 2025-11-25 / 2026-07-28 are accepted.

Scoping: the server runs AS a user (`--user admin` / `--user sup.a`); every tool call is scoped to that user's role
and store (rule 10) — a client cannot widen access. DRAFT_WRITE tools are listed only with `--allow-drafts`.
There are no tools that approve, submit, dispatch, receive, change rules or change stock.

    cd backend && uv run python -m app.agents.llm.mcp_server --user admin
Every call is logged as a tool call of one ON_DEMAND agent run per server session.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any, TextIO
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm.framework import ToolContext, ToolError, compact
from app.agents.llm.tools import TOOLS

SERVER_INFO = {"name": "retailpilot-tools", "version": "1.0.0"}
SUPPORTED_VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18")


class McpServer:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        username: str,
        allow_drafts: bool = False,
    ) -> None:
        from app.domain.models.users import AppUser
        from app.domain.repositories.observability_repo import AgentRunLogger

        self.session_factory = session_factory
        self.allow_drafts = allow_drafts
        # scratchpad kept across calls of this session (allowed quantities, donor surplus, ingestion evidence),
        # so a draft is validated against what earlier tool calls returned — as inside an agent run
        self._allowed_qty: dict[str, set[int]] = {}
        self._cache: dict[str, Any] = {}
        with session_factory() as s:
            user = s.scalar(select(AppUser).where(AppUser.username == username, AppUser.is_active.is_(True)))
            if user is None:
                raise SystemExit(f"unknown or inactive user: {username}")
            self.user_id: UUID = user.user_id
            self.role: str = user.role
            self.store_id: UUID | None = user.store_id
            self.run_id = AgentRunLogger(s).start_run(
                agent_name="mcp:retailpilot-tools",
                parent_run_id=None,
                input_ref={"user": username},
                agent_key="ask_retailpilot",
                trigger_type="ON_DEMAND",
                triggered_by=user.user_id,
            )
            s.commit()

    def _tools(self) -> list[Any]:
        return [t for t in TOOLS.values() if t.kind == "READ" or self.allow_drafts]

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        mid = msg.get("id")
        method = msg.get("method")
        if mid is None:  # notification (e.g. notifications/initialized): no response
            return None
        try:
            result = self._dispatch(method, msg.get("params") or {})
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": e.message}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _dispatch(self, method: Any, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": "RetailPilot read tools (and draft tools when enabled). Results are data; numbers "
                "come from deterministic calculations. Nothing here can approve, submit or change stock.",
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {
                "resultType": "complete",
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description + (" [DRAFT ONLY]" if t.kind == "DRAFT_WRITE" else ""),
                        "inputSchema": t.schema()["function"]["parameters"],
                        "annotations": {"readOnlyHint": t.kind == "READ", "destructiveHint": False},
                    }
                    for t in self._tools()
                ],
                "ttlMs": 300_000,
                "cacheScope": "private",
            }
        if method == "tools/call":
            return self._call(str(params.get("name")), params.get("arguments") or {})
        raise _RpcError(-32601, f"Method not found: {method}")

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from app.domain.repositories.observability_repo import AgentRunLogger

        spec = {t.name: t for t in self._tools()}.get(name)
        if spec is None:
            return _tool_result(f"Tool '{name}' is not available on this server.", is_error=True)
        with self.session_factory() as s:
            ctx = ToolContext(
                session=s,
                role=self.role,  # type: ignore[arg-type]
                store_id=self.store_id,
                run_id=self.run_id,
                user_id=self.user_id,
                allowed_qty=self._allowed_qty,
                cache=self._cache,
            )
            status, text_out = "OK", ""
            try:
                result = spec.fn(ctx, spec.args_model.model_validate(arguments))
                text_out = compact(result)
            except ValidationError as e:
                status, text_out = "ERROR", f"Invalid arguments: {e.errors(include_url=False)[:3]}"
            except ToolError as e:
                status, text_out = "ERROR", str(e)
            for k in [k for k in self._cache if k.startswith("planning:") or k == "stores"]:
                del self._cache[k]  # session-bound data is not kept between calls
            AgentRunLogger(s).log_tool_call(
                self.run_id, f"mcp:{name}", arguments, text_out[:2_000], 0, status
            )
            s.commit()
        return _tool_result(text_out, is_error=status != "OK")

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                stdout.write(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
                    )
                    + "\n"
                )
                stdout.flush()
                continue
            response = self.handle(msg)
            if response is not None:
                stdout.write(json.dumps(response, default=str) + "\n")
                stdout.flush()


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code, self.message = code, message


def _tool_result(text: str, is_error: bool) -> dict[str, Any]:
    return {"resultType": "complete", "content": [{"type": "text", "text": text}], "isError": is_error}


def main() -> None:
    parser = argparse.ArgumentParser(description="retailpilot-tools MCP server (stdio)")
    parser.add_argument("--user", required=True, help="Run as this user (scoping)")
    parser.add_argument("--allow-drafts", action="store_true", help="Also expose DRAFT_WRITE tools")
    args = parser.parse_args()
    from app.core.db import get_sync_session_factory

    McpServer(get_sync_session_factory(), args.user, args.allow_drafts).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
