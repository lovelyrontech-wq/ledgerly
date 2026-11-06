"""MCP server: tools act as the signed-in user, the agent cannot approve on its own,
and the HTTP endpoint rejects requests without a valid login token."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.types import CallToolResult, TextContent
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.config import Settings
from ledgerly.knowledge.help_docs import HelpDocs
from ledgerly.mcp_server.server import build_server
from ledgerly.permissions import Role
from ledgerly.security import create_access_token
from ledgerly.services.batches import load_batch, preview_hash
from tests.conftest import TEST_SECRET

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "list_folders",
    "list_records",
    "preview_bulk_update",
    "apply_bulk_update",
    "undo_batch",
    "search_help_docs",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def call(
    settings: Settings, seeded: sessionmaker[Session], user: str, tool: str, args: dict[str, Any]
) -> CallToolResult:
    server = build_server(settings, seeded, current_user=lambda: user)
    async with Client(server) as client:
        return await client.call_tool(tool, args)


def data(result: CallToolResult) -> Any:
    assert not result.is_error, _text(result)
    return result.structured_content or json.loads(_text(result))


def _text(result: CallToolResult) -> str:
    return "".join(c.text for c in result.content if isinstance(c, TextContent))


def approval_code(seeded: sessionmaker[Session], batch_id: str) -> str:
    """What the app gets from GET /api/batches/{id} and sends when the user clicks Approve."""
    with seeded() as session:
        batch = load_batch(session, "usr_alice", batch_id, Role.VIEWER)
        return preview_hash(batch.id, batch.items)


async def test_lists_all_tools(settings: Settings, seeded: sessionmaker[Session]) -> None:
    async with Client(build_server(settings, seeded, current_user=lambda: "usr_alice")) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == EXPECTED_TOOLS


async def test_tools_only_see_the_users_folders(settings: Settings, seeded: sessionmaker[Session]) -> None:
    carol = data(await call(settings, seeded, "usr_carol", "list_folders", {}))
    assert [f["id"] for f in carol["folders"]] == ["fld_q3_invoices"]

    hidden = await call(settings, seeded, "usr_alice", "list_records", {"folder_id": "fld_bob_invoices"})
    assert hidden.is_error
    assert "not found" in _text(hidden).lower()


async def test_list_records_caps_results(settings: Settings, seeded: sessionmaker[Session]) -> None:
    page = data(
        await call(settings, seeded, "usr_carol", "list_records", {"folder_id": "fld_q3_invoices", "limit": 10})
    )
    assert page["total"] == 40
    assert len(page["records"]) == 10
    assert page["records"][0]["value"].endswith("USD")


async def test_preview_does_not_reveal_approval_code(settings: Settings, seeded: sessionmaker[Session]) -> None:
    preview = data(
        await call(
            settings,
            seeded,
            "usr_alice",
            "preview_bulk_update",
            {"folder_id": "fld_q3_invoices", "percent": 10, "instruction": "update the values in this folder by 10%"},
        )
    )

    assert preview["status"] == "pending"
    assert preview["recordCount"] == 40
    assert preview["summary"] == {"pending": 40}
    assert approval_code(seeded, preview["batchId"]) not in json.dumps(preview)
    assert "approve" in preview["message"].lower()


async def test_agent_cannot_apply_without_users_approval(settings: Settings, seeded: sessionmaker[Session]) -> None:
    preview = data(
        await call(
            settings,
            seeded,
            "usr_alice",
            "preview_bulk_update",
            {"folder_id": "fld_q3_invoices", "percent": 10, "instruction": "x"},
        )
    )

    guessed = await call(
        settings, seeded, "usr_alice", "apply_bulk_update", {"batch_id": preview["batchId"], "approval_code": "a" * 64}
    )

    assert guessed.is_error
    assert "does not match" in _text(guessed)


async def test_apply_and_undo_with_approval(settings: Settings, seeded: sessionmaker[Session]) -> None:
    preview = data(
        await call(
            settings,
            seeded,
            "usr_alice",
            "preview_bulk_update",
            {"folder_id": "fld_q3_invoices", "percent": 10, "instruction": "x"},
        )
    )
    args = {"batch_id": preview["batchId"], "approval_code": approval_code(seeded, preview["batchId"])}

    applied = data(await call(settings, seeded, "usr_alice", "apply_bulk_update", args))
    retried = data(await call(settings, seeded, "usr_alice", "apply_bulk_update", args))
    undone = data(await call(settings, seeded, "usr_alice", "undo_batch", {"batch_id": preview["batchId"]}))

    assert applied["summary"] == {"applied": 40}
    assert retried["summary"] == {"applied": 40}  # same approval again: no second apply
    assert undone["summary"] == {"undone": 40}


async def test_viewer_cannot_preview(settings: Settings, seeded: sessionmaker[Session]) -> None:
    result = await call(
        settings,
        seeded,
        "usr_carol",
        "preview_bulk_update",
        {"folder_id": "fld_q3_invoices", "percent": 10, "instruction": "x"},
    )
    assert result.is_error
    assert "editor" in _text(result)


async def test_bad_arguments_are_errors(settings: Settings, seeded: sessionmaker[Session]) -> None:
    result = await call(
        settings,
        seeded,
        "usr_alice",
        "preview_bulk_update",
        {"folder_id": "fld_q3_invoices", "percent": 5000, "instruction": "x"},
    )
    assert result.is_error


async def test_search_help_docs(settings: Settings, seeded: sessionmaker[Session]) -> None:
    found = data(
        await call(settings, seeded, "usr_alice", "search_help_docs", {"query": "how do I undo a bulk update?"})
    )
    assert found["results"]
    assert found["results"][0]["source"] == "undo-and-history.md"


@pytest.mark.parametrize(
    ("query", "source"),
    [
        ("share a folder with a teammate", "sharing-and-permissions.md"),
        ("how is rounding done", "bulk-updates.md"),
        ("export records to csv", "import-export.md"),
    ],
)
def test_help_search_finds_the_right_article(settings: Settings, query: str, source: str) -> None:
    results = HelpDocs.load(settings.data_dir / "help-docs").search(query)
    assert results[0].source == source


def test_help_search_with_no_match_is_empty(settings: Settings) -> None:
    assert HelpDocs.load(settings.data_dir / "help-docs").search("zzzz qqqq") == []


# ---------- HTTP endpoint and login token ----------
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def http_client(settings: Settings, seeded: sessionmaker[Session]) -> TestClient:
    app = build_server(settings, seeded).streamable_http_app(json_response=True, stateless_http=True)
    return TestClient(app, base_url="http://localhost:8001")


@pytest.mark.parametrize("token", [None, "not-a-token"])
def test_http_rejects_missing_or_bad_token(
    settings: Settings, seeded: sessionmaker[Session], token: str | None
) -> None:
    headers = dict(MCP_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with http_client(settings, seeded) as client:
        response = client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 401


def test_http_accepts_app_login_token(settings: Settings, seeded: sessionmaker[Session]) -> None:
    token = create_access_token("usr_alice", TEST_SECRET, ttl_minutes=5)
    with http_client(settings, seeded) as client:
        response = client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["name"] == "ledgerly"
