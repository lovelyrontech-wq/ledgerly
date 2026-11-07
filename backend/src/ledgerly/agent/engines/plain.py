"""Engine 1: a plain loop. Ask the model, run the tools it asks for, repeat, at most N times."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ledgerly.agent.base import (
    AgentEvent,
    AgentRun,
    ApprovalRequiredEvent,
    LlmReply,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from ledgerly.agent.prompt import SYSTEM_PROMPT

class PlainEngine:
    name = "plain"

    def __init__(self, max_steps: int = 6) -> None:
        self._max_steps = max_steps

    async def chat(self, run: AgentRun, message: str) -> AsyncIterator[AgentEvent]:
        conversation = run.conversation
        for note in conversation.take_notes():
            conversation.add(note)
        conversation.add({"role": "user", "content": message})

        for _ in range(self._max_steps):
            messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *conversation.messages]
            reply: LlmReply | None = None
            async for item in run.stream_llm(messages):
                if isinstance(item, TokenEvent):
                    yield item
                else:
                    reply = item
            assert reply is not None

            conversation.add(
                {
                    "role": "assistant",
                    "content": reply.text,
                    "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in reply.tool_calls],
                }
            )
            if not reply.tool_calls:
                run.stop = "approval_required" if conversation.pending_batch_id else "answer"
                return

            for call in reply.tool_calls:
                yield ToolCallEvent(call.name, call.arguments)
                outcome = await run.call_tool(call.name, call.arguments)
                yield ToolResultEvent(call.name, outcome.ok, outcome.data, round(outcome.duration_ms, 1))
                conversation.add({"role": "tool", "tool_name": call.name, "content": outcome.for_model()})
                if call.name == "preview_bulk_update" and outcome.ok:
                    conversation.pending_batch_id = outcome.data["batchId"]
                    yield ApprovalRequiredEvent(outcome.data["batchId"], outcome.data)

        # Out of steps. A preview made on the way still waits for the user.
        run.stop = "approval_required" if conversation.pending_batch_id else "max_steps"

    async def approve(self, run: AgentRun, batch_id: str, approval_code: str) -> AsyncIterator[AgentEvent]:
        # No model call: the user already decided. The approval code goes to the tool only,
        # never into the conversation the model reads.
        args = {"batch_id": batch_id, "approval_code": approval_code}
        yield ToolCallEvent("apply_bulk_update", {"batch_id": batch_id})
        outcome = await run.call_tool("apply_bulk_update", args, server_only=True)
        yield ToolResultEvent("apply_bulk_update", outcome.ok, outcome.data, round(outcome.duration_ms, 1))
        if outcome.ok:
            run.conversation.pending_batch_id = None
        note = apply_note(batch_id, outcome.ok, outcome.data)
        run.conversation.add({"role": "assistant", "content": note})
        yield TokenEvent(note)
        run.stop = "applied" if outcome.ok else "error"

def apply_note(batch_id: str, ok: bool, data: dict[str, Any]) -> str:
    """What the assistant says after an approval. Shared by both engines."""
    if not ok:
        return f"I could not apply batch {batch_id}: {data.get('error', 'unknown error')}"
    counts = ", ".join(f"{n} {result.replace('_', ' ')}" for result, n in (data.get("summary") or {}).items())
    return f"Done: batch {batch_id} is applied ({counts}). {data.get('message', '')}".strip()