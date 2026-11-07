"""The agent's connection to the Ledgerly MCP server.

The agent connects with the signed-in user's login token, so every tool runs as that user with
their folder permissions. The model never gets apply_bulk_update: only the server applies a
batch, after the user clicks Approve (see the /api/agent/approve route).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent

# Tools the model may call. apply_bulk_update is left out on purpose.
MODEL_TOOLS = ("list_folders", "list_records", "preview_bulk_update", "undo_batch", "search_help_docs")

# Longest tool result (JSON characters) put into the model's context.
MAX_RESULT_CHARS = 6000
# Per-record rows of a batch shown to the model. The UI gets them all; the model only needs the
# counts and totals, and fewer tokens make a local model much faster.
MAX_CHANGES_FOR_MODEL = 5

@dataclass(frozen=True)
class ToolOutcome:
    name: str
    ok: bool
    data: dict[str, Any]  # the tool's JSON result, or {"error": "..."}
    duration_ms: float

    def for_model(self) -> str:
        data = self.data
        changes = data.get("changes")
        if isinstance(changes, list) and len(changes) > MAX_CHANGES_FOR_MODEL:
            hidden = len(changes) - MAX_CHANGES_FOR_MODEL + int(data.get("changesNotShown", 0))
            data = {**data, "changes": changes[:MAX_CHANGES_FOR_MODEL], "changesNotShown": hidden}
        text = json.dumps(data, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + '... (cut off: ask for fewer records with limit/offset)"'
        return text

def _text(result: CallToolResult) -> str:
    return "".join(c.text for c in result.content if isinstance(c, TextContent))


def _to_data(result: CallToolResult) -> dict[str, Any]:
    if result.is_error:
        return {"error": _text(result) or "The tool failed."}
    if isinstance(result.structured_content, dict):
        return result.structured_content
    try:
        parsed = json.loads(_text(result))
    except json.JSONDecodeError:
        return {"text": _text(result)}
    return parsed if isinstance(parsed, dict) else {"result": parsed}

class Toolbox:
    """MCP tools for one request: their specs (for the model) and a way to call them."""

    def __init__(self, client: Client, specs: list[dict[str, Any]]) -> None:
        self._client = client
        self.specs = specs  # Ollama/OpenAI function-calling format, MODEL_TOOLS only

    @classmethod
    async def load(cls, client: Client) -> Toolbox:
        listed = await client.list_tools()
        specs = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
            for tool in listed.tools
            if tool.name in MODEL_TOOLS
        ]
        return cls(client, specs)

    async def call(self, name: str, arguments: dict[str, Any], *, server_only: bool = False) -> ToolOutcome:
        """Call a tool. `server_only=True` allows tools the model is not given (apply_bulk_update)."""
        started = time.perf_counter()
        if not server_only and name not in MODEL_TOOLS:
            return ToolOutcome(name, False, {"error": f"Unknown tool {name!r}."}, 0.0)
        try:
            result = await self._client.call_tool(name, arguments)
            data, ok = _to_data(result), not result.is_error
        except MCPError as exc:
            data, ok = {"error": str(exc)}, False
        return ToolOutcome(name, ok, data, (time.perf_counter() - started) * 1000)

# Opens a Toolbox for (user ID, login token). Tests replace it with an in-process server.
ToolboxFactory = Callable[[str, str], AbstractAsyncContextManager[Toolbox]]


def http_toolbox_factory(mcp_url: str, timeout_seconds: float = 60.0) -> ToolboxFactory:
    @asynccontextmanager
    async def open_toolbox(_user_id: str, token: str) -> AsyncIterator[Toolbox]:
        timeout = httpx2.Timeout(timeout_seconds, read=timeout_seconds)
        async with (
            httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=timeout) as http,
            Client(streamable_http_client(mcp_url, http_client=http)) as client,
        ):
            yield await Toolbox.load(client)

    return open_toolbox