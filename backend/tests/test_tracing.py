"""LangSmith tracing (step 7): what gets sent, for both engines, without a network or Ollama.

A recording langsmith Client stands in for LangSmith; a scripted model and in-memory tools stand in
for Ollama and the MCP server.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from langsmith import Client
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.agent import AgentServices
from ledgerly.agent.base import LlmChunk, LlmStats, LlmToolCall
from ledgerly.agent.conversations import ConversationStore
from ledgerly.agent.mcp_client import ToolOutcome
from ledgerly.agent.registry import build_engines
from ledgerly.api.app import create_app
from ledgerly.config import Settings
from ledgerly.observability import Tracer, build_tracer, redact
from ledgerly.observability.tracing import REDACTED

from .conftest import TEST_PASSWORD

FOLDER = "fld_q3_invoices"


class RecordingClient(Client):
    """Keeps every run instead of sending it."""

    def __init__(self) -> None:
        super().__init__(api_url="http://langsmith.invalid", api_key="test-key", auto_batch_tracing=False)
        self.recorded: dict[str, dict[str, Any]] = {}

    def create_run(self, name: str, inputs: dict[str, Any], run_type: str, **kwargs: Any) -> None:
        run_id = str(kwargs["id"])
        self.recorded[run_id] = {"name": name, "inputs": inputs, "run_type": run_type, **kwargs}

    def update_run(self, run_id: Any, **kwargs: Any) -> None:
        self.recorded.setdefault(str(run_id), {}).update({k: v for k, v in kwargs.items() if v is not None})

    def flush(self) -> None:
        pass

    def named(self, name: str) -> list[dict[str, Any]]:
        return [run for run in self.recorded.values() if run.get("name") == name]

    def children_of(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        """Every run below `run` (any depth), by trace id and dotted order."""
        return [
            r
            for r in self.recorded.values()
            if r.get("trace_id") == run["trace_id"] and r is not run and str(r.get("dotted_order", "")).startswith(
                str(run["dotted_order"])
            )
        ]


class ScriptedLlm:
    """First call: ask for a preview. Every later call: a short answer."""

    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[LlmChunk]:
        self.calls += 1
        stats = LlmStats(prompt_tokens=100, output_tokens=10, model_ms=50.0)
        if self.calls == 1:
            args = {"folder_id": FOLDER, "percent": 10, "instruction": "raise drafts", "status": "draft"}
            yield LlmChunk(tool_calls=[LlmToolCall("preview_bulk_update", args)], stats=stats)
        else:
            yield LlmChunk(text="Preview ready. ")
            yield LlmChunk(text="Please approve.", stats=stats)


class FakeToolbox:
    specs: ClassVar[list[dict[str, Any]]] = [
        {"type": "function", "function": {"name": "preview_bulk_update", "parameters": {}}}
    ]

    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any], *, server_only: bool = False) -> ToolOutcome:
        self.calls.append((name, arguments))
        data = {"batchId": self.batch_id, "status": "applied" if name == "apply_bulk_update" else "pending",
                "summary": {"applied": 1}, "recordCount": 1}
        return ToolOutcome(name, True, data, 1.0)


@pytest.fixture
def recorder() -> RecordingClient:
    return RecordingClient()


def _app(settings: Settings, seeded: sessionmaker[Session], recorder: RecordingClient, toolbox: FakeToolbox) -> Any:
    @asynccontextmanager
    async def open_toolbox(_user_id: str, _token: str) -> AsyncIterator[FakeToolbox]:
        yield toolbox

    services = AgentServices(
        engines=build_engines(settings),
        llm=ScriptedLlm(),
        open_toolbox=open_toolbox,  # type: ignore[arg-type]
        conversations=ConversationStore(10),
        tracer=Tracer(recorder, "test-project"),
    )
    return create_app(settings=settings, session_factory=seeded, agent_services=services)


def _sse(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def agent_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"agent_engines_enabled": ["plain", "langgraph"], "agent_checkpoint_db": ":memory:"}
    )


@pytest.fixture
def signed_in(agent_settings: Settings, seeded: sessionmaker[Session], recorder: RecordingClient) -> Iterator[
    tuple[TestClient, dict[str, str], FakeToolbox]
]:
    toolbox = FakeToolbox("pending")
    with TestClient(_app(agent_settings, seeded, recorder, toolbox)) as client:
        login = client.post("/api/auth/login", json={"email": "alice@ledgerly.test", "password": TEST_PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        # A real batch, so /approve can look up its approval code.
        preview = client.post(
            f"/api/folders/{FOLDER}/batches/preview",
            json={"percent": 10, "instruction": "raise drafts", "status": "draft"},
            headers=headers,
        )
        toolbox.batch_id = preview.json()["id"]
        yield client, headers, toolbox


@pytest.mark.parametrize("engine_name", ["plain", "langgraph"])
def test_chat_and_approve_are_traced_with_engine_tag(
    signed_in: tuple[TestClient, dict[str, str], FakeToolbox], recorder: RecordingClient, engine_name: str
) -> None:
    client, headers, toolbox = signed_in
    chat = client.post(
        "/api/agent/chat",
        json={"message": "raise drafts by 10%", "folderId": FOLDER},
        headers={**headers, "X-Agent-Engine": engine_name},
    )
    events = _sse(chat.text)
    done = events[-1]
    assert done["stop"] == "approval_required"

    [root] = recorder.named("agent.chat")
    assert root["run_type"] == "chain"
    assert root["inputs"] == {"message": "raise drafts by 10%", "folderId": FOLDER}
    assert f"engine:{engine_name}" in root["tags"] and "stop:approval_required" in root["tags"]
    assert root["outputs"]["answer"] == "Preview ready. Please approve."
    assert root["outputs"]["metrics"]["llmCalls"] == 2
    assert root["extra"]["metadata"]["conversation_id"] == done["conversationId"]
    assert root["extra"]["metadata"]["llmCalls"] == 2  # filterable in LangSmith
    assert not root.get("error")

    below = recorder.children_of(root)
    llm_runs = [r for r in below if r["name"] == "ollama.chat"]
    tool_runs = [r for r in below if r["name"] == "preview_bulk_update" and r["run_type"] == "tool"]
    assert len(llm_runs) == 2 and all(r["run_type"] == "llm" for r in llm_runs)
    assert llm_runs[0]["extra"]["metadata"]["ls_model_name"] == "fake-model"
    assert any(r["outputs"].get("usage_metadata", {}).get("input_tokens") == 100 for r in llm_runs)
    assert len(tool_runs) == 1 and tool_runs[0]["inputs"]["status"] == "draft"

    approve = client.post(
        "/api/agent/approve",
        json={"conversationId": done["conversationId"], "batchId": toolbox.batch_id},
        headers=headers,
    )
    assert _sse(approve.text)[-1]["stop"] == "applied"

    # The tool really got the approval code, but the trace never shows it.
    [(_, applied_args)] = [c for c in toolbox.calls if c[0] == "apply_bulk_update"]
    assert len(applied_args["approval_code"]) == 64
    [approve_root] = recorder.named("agent.approve")
    assert approve_root["inputs"] == {"batchId": toolbox.batch_id}
    assert f"engine:{engine_name}" in approve_root["tags"]
    everything = json.dumps(list(recorder.recorded.values()), default=str)
    assert applied_args["approval_code"] not in everything


def test_failed_run_is_marked_as_error(
    signed_in: tuple[TestClient, dict[str, str], FakeToolbox], recorder: RecordingClient
) -> None:
    client, headers, _ = signed_in

    async def broken(*_: Any) -> AsyncIterator[LlmChunk]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    client.app.state.agent.llm.stream_chat = broken  # type: ignore[attr-defined]
    events = _sse(client.post("/api/agent/chat", json={"message": "hi"}, headers=headers).text)
    assert events[-1]["stop"] == "error"
    [root] = recorder.named("agent.chat")
    assert "Something went wrong" in root["error"]
    assert "stop:error" in root["tags"]


def test_redact_hides_the_approval_code() -> None:
    assert redact({"batch_id": "b1", "approval_code": "x" * 64}) == {"batch_id": "b1", "approval_code": REDACTED}


def test_tracing_is_off_without_flag_or_key(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    assert not build_tracer(settings.model_copy(update={"langsmith_tracing": False})).enabled
    no_key = settings.model_copy(update={"langsmith_tracing": True, "langsmith_api_key": None})
    assert not build_tracer(no_key).enabled
    assert "LANGSMITH_API_KEY is empty" in caplog.text
    on = settings.model_copy(update={"langsmith_tracing": True, "langsmith_api_key": SecretStr("lsv2_test")})
    tracer = build_tracer(on)
    assert tracer.enabled and tracer.project == settings.langsmith_project


def test_disabled_tracer_spans_do_nothing() -> None:
    with Tracer.disabled().span("x", "chain", {"a": 1}) as span:
        span.add_outputs({"b": 2})
        span.add_tags(["t"])
        span.add_metadata({"m": 1})
        span.fail("nope")
