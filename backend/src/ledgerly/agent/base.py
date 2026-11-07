"""What every agent engine shares: the events it streams, the model interface, and the run context.

Both engines (plain loop and LangGraph) call the model and the tools only through AgentRun, so
they are measured the same way and the speed comparison is fair.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ledgerly.agent.conversations import Conversation
from ledgerly.agent.mcp_client import Toolbox, ToolOutcome
from ledgerly.agent.metrics import RunMetrics

# ---------- Events streamed to the browser (one SSE event each) ----------
@dataclass(frozen=True)
class TokenEvent:
    """A piece of the assistant's answer, as the model writes it."""

    text: str
    type: Literal["token"] = "token"

@dataclass(frozen=True)
class ToolCallEvent:
    name: str
    arguments: dict[str, Any]
    type: Literal["tool_call"] = "tool_call"

@dataclass(frozen=True)
class ToolResultEvent:
    name: str
    ok: bool
    result: dict[str, Any]
    duration_ms: float
    type: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class ApprovalRequiredEvent:
    """A preview is waiting for the user. The UI shows it with an Approve button."""

    batch_id: str
    preview: dict[str, Any]
    type: Literal["approval_required"] = "approval_required"


@dataclass(frozen=True)
class ErrorEvent:
    message: str
    type: Literal["error"] = "error"


StopReason = Literal["answer", "approval_required", "applied", "max_steps", "error"]


@dataclass(frozen=True)
class DoneEvent:
    """Always the last event. `stop` says why the run ended."""

    conversation_id: str
    engine: str
    stop: StopReason
    pending_batch_id: str | None
    metrics: dict[str, Any]
    type: Literal["done"] = "done"

AgentEvent = TokenEvent | ToolCallEvent | ToolResultEvent | ApprovalRequiredEvent | ErrorEvent | DoneEvent

# ---------- The model ----------


class LlmUnavailable(Exception):
    """The model server could not be reached or rejected the request."""


@dataclass(frozen=True)
class LlmToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LlmStats:
    """From the model server: tokens read, tokens written, and time spent in the model."""

    prompt_tokens: int
    output_tokens: int
    model_ms: float


@dataclass(frozen=True)
class LlmChunk:
    text: str = ""
    tool_calls: Sequence[LlmToolCall] = ()
    stats: LlmStats | None = None  # set on the last chunk only


class LlmClient(Protocol):
    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[LlmChunk]:
        """Stream one model reply. Raises LlmUnavailable if the model cannot be reached."""
        ...


@dataclass
class LlmReply:
    text: str
    tool_calls: list[LlmToolCall]

# ---------- One request: conversation + tools + model + metrics ----------
@dataclass
class AgentRun:
    conversation: Conversation
    toolbox: Toolbox
    llm: LlmClient
    metrics: RunMetrics = field(default_factory=RunMetrics)
    stop: StopReason = "answer"  # the engine sets this before it returns

    async def stream_llm(self, messages: list[dict[str, Any]]) -> AsyncIterator[TokenEvent | LlmReply]:
        """Call the model once. Yields TokenEvents as text arrives, then one LlmReply."""
        text: list[str] = []
        calls: list[LlmToolCall] = []
        stats: LlmStats | None = None
        self.metrics.llm_started()
        async for chunk in self.llm.stream_chat(messages, self.toolbox.specs):
            if chunk.text:
                self.metrics.first_token()
                text.append(chunk.text)
                yield TokenEvent(chunk.text)
            calls.extend(chunk.tool_calls)
            if chunk.stats is not None:
                stats = chunk.stats
        self.metrics.llm_finished(stats)
        yield LlmReply("".join(text), calls)

    async def call_tool(self, name: str, arguments: dict[str, Any], *, server_only: bool = False) -> ToolOutcome:
        outcome = await self.toolbox.call(name, arguments, server_only=server_only)
        self.metrics.tool_finished(outcome.duration_ms)
        return outcome

class AgentEngine(Protocol):
    name: str

    def chat(self, run: AgentRun, message: str) -> AsyncIterator[AgentEvent]:
        """Answer one user message. May end with an ApprovalRequiredEvent. Must not yield DoneEvent."""
        ...

    def approve(self, run: AgentRun, batch_id: str, approval_code: str) -> AsyncIterator[AgentEvent]:
        """The user approved the pending batch: apply it. Must not yield DoneEvent."""

        ...
