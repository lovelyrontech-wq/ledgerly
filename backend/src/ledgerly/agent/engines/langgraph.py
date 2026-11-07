"""Engine 2: the same agent as a LangGraph graph.

    START -> agent --(tool calls)--> tools -> agent ...
               |
               +--(no tool calls, a preview is pending)--> approval --[interrupt]--> pause
               +--(no tool calls, nothing pending / step limit)--> END

The approval node calls interrupt(), so the graph pauses and its state is saved in the SQLite
checkpointer under the conversation ID. Approve resumes it with Command(resume=...).

Fair comparison with the plain engine: the same model client, system prompt, tools and history
window, and the model and tools are called only through AgentRun, so metrics are measured the
same way. What differs is only the orchestration (graph, checkpoints, interrupt/resume).

The approval code goes in the run context, which LangGraph does not save, so it never lands in
the checkpoint database, and the model never sees it.
"""

from __future__ import annotations

import asyncio
import operator
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from ledgerly.agent.base import (
    AgentEvent,
    AgentRun,
    ApprovalRequiredEvent,
    ErrorEvent,
    LlmReply,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from ledgerly.agent.conversations import keep_recent
from ledgerly.agent.engines.plain import apply_note
from ledgerly.agent.prompt import SYSTEM_PROMPT


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]  # nodes return only the new messages
    pending_batch_id: str | None
    steps: int  # model calls in this turn
    last_tool_calls: list[dict[str, Any]]

@dataclass
class RunContext:
    """Per request, not saved in checkpoints."""

    run: AgentRun
    max_steps: int
    approval_code: str | None = None


# ---------- Nodes ----------

async def agent_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentState:
    run = runtime.context.run
    write = get_stream_writer()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *keep_recent(state["messages"])]
    reply: LlmReply | None = None
    async for item in run.stream_llm(messages):
        if isinstance(item, TokenEvent):
            write(item)
        else:
            reply = item
    assert reply is not None
    calls = [{"name": c.name, "arguments": c.arguments} for c in reply.tool_calls]
    return {
        "messages": [{"role": "assistant", "content": reply.text, "tool_calls": [{"function": c} for c in calls]}],
        "steps": state.get("steps", 0) + 1,
        "last_tool_calls": calls,
    }

async def tools_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentState:
    run = runtime.context.run
    write = get_stream_writer()
    new_messages: list[dict[str, Any]] = []
    pending = state.get("pending_batch_id")
    for call in state.get("last_tool_calls", []):
        write(ToolCallEvent(call["name"], call["arguments"]))
        outcome = await run.call_tool(call["name"], call["arguments"])
        write(ToolResultEvent(call["name"], outcome.ok, outcome.data, round(outcome.duration_ms, 1)))
        new_messages.append({"role": "tool", "tool_name": call["name"], "content": outcome.for_model()})
        if call["name"] == "preview_bulk_update" and outcome.ok:
            pending = outcome.data["batchId"]
            run.conversation.pending_batch_id = pending
            write(ApprovalRequiredEvent(pending, outcome.data))
    return {"messages": new_messages, "pending_batch_id": pending, "last_tool_calls": []}


async def approval_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentState:
    batch_id = state["pending_batch_id"]
    assert batch_id is not None
    # Pause here. Everything above runs again on resume, so nothing above may have side effects.
    interrupt({"batchId": batch_id})

    ctx = runtime.context
    run, write = ctx.run, get_stream_writer()
    if ctx.approval_code is None:  # resumed without an approval: should not happen
        raise RuntimeError("Resumed without an approval code")
    write(ToolCallEvent("apply_bulk_update", {"batch_id": batch_id}))
    args = {"batch_id": batch_id, "approval_code": ctx.approval_code}
    outcome = await run.call_tool("apply_bulk_update", args, server_only=True)
    write(ToolResultEvent("apply_bulk_update", outcome.ok, outcome.data, round(outcome.duration_ms, 1)))
    note = apply_note(batch_id, outcome.ok, outcome.data)
    write(TokenEvent(note))
    run.stop = "applied" if outcome.ok else "error"
    pending = None if outcome.ok else batch_id  # failed: stays pending, can be approved again
    run.conversation.pending_batch_id = pending
    return {"messages": [{"role": "assistant", "content": note}], "pending_batch_id": pending}


# ---------- Edges ----------


def after_agent(state: AgentState, runtime: Runtime[RunContext]) -> str:
    if state.get("last_tool_calls"):
        return "tools"
    return "approval" if state.get("pending_batch_id") else END


def after_tools(state: AgentState, runtime: Runtime[RunContext]) -> str:
    if state.get("steps", 0) >= runtime.context.max_steps:
        if state.get("pending_batch_id"):
            return "approval"  # out of steps, but a preview still waits for the user
        runtime.context.run.stop = "max_steps"
        return END
    return "agent"


def after_approval(state: AgentState, runtime: Runtime[RunContext]) -> str:
    return "approval" if state.get("pending_batch_id") else END  # failed apply: wait for another approval


def build_graph() -> StateGraph[AgentState, RunContext, AgentState, AgentState]:
    graph = StateGraph(AgentState, context_schema=RunContext)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("approval", approval_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", "approval", END])
    graph.add_conditional_edges("tools", after_tools, ["agent", "approval", END])
    graph.add_conditional_edges("approval", after_approval, ["approval", END])
    return graph


# ---------- Engine ----------


class LangGraphEngine:
    name = "langgraph"

    def __init__(self, checkpoint_db: str | Path, max_steps: int = 6) -> None:
        self._checkpoint_db = str(checkpoint_db)
        self._max_steps = max_steps
        self._conn: aiosqlite.Connection | None = None
        self._graph: CompiledStateGraph[AgentState, RunContext, AgentState, AgentState] | None = None
        self._lock = asyncio.Lock()

    async def _compiled(self) -> CompiledStateGraph[AgentState, RunContext, AgentState, AgentState]:
        # Opened on first use, inside the server's event loop.
        async with self._lock:
            if self._graph is None:
                self._conn = await aiosqlite.connect(self._checkpoint_db)
                saver = AsyncSqliteSaver(self._conn)
                await saver.setup()
                self._graph = build_graph().compile(checkpointer=saver)
            return self._graph

    async def aclose(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn, self._graph = None, None

    async def _stream(self, graph_input: Any, run: AgentRun, approval_code: str | None) -> AsyncIterator[AgentEvent]:
        graph = await self._compiled()
        config: RunnableConfig = {"configurable": {"thread_id": run.conversation.id}}
        if isinstance(graph_input, Command):
            state = await graph.aget_state(config)
            if not state.interrupts:
                yield ErrorEvent("Nothing in this conversation is waiting for approval.")
                run.stop = "error"
                return
        context = RunContext(run=run, max_steps=self._max_steps, approval_code=approval_code)
        interrupted = False
        async for mode, chunk in graph.astream(graph_input, config, context=context, stream_mode=["custom", "updates"]):
            if mode == "custom":
                yield cast(AgentEvent, chunk)  # nodes only write AgentEvents
            elif isinstance(chunk, dict) and "__interrupt__" in chunk:
                interrupted = True
        if interrupted and run.stop == "answer":
            run.stop = "approval_required"

    def chat(self, run: AgentRun, message: str) -> AsyncIterator[AgentEvent]:
        # "answer" unless a node or the interrupt says otherwise.
        run.stop = "answer"
        new_turn = {"messages": [{"role": "user", "content": message}], "steps": 0, "last_tool_calls": []}
        return self._stream(new_turn, run, approval_code=None)

    def approve(self, run: AgentRun, batch_id: str, approval_code: str) -> AsyncIterator[AgentEvent]:
        # The route already checked batch_id is this conversation's pending batch.
        return self._stream(Command(resume={"approved": True}), run, approval_code=approval_code)