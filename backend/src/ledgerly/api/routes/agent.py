"""The in-app agent.

POST /api/agent/chat     send a message; the answer streams back as Server-Sent Events
POST /api/agent/approve  the user clicked Approve on the pending preview; applies it (SSE)
POST /api/agent/undo     undo an applied batch from the chat (JSON)

Pick an engine per request with the header `X-Agent-Engine: plain|langgraph` (enabled ones only).
A conversation stays on the engine it started with.

SSE events: token, tool_call, tool_result, approval_required, error, then always done (with metrics).
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

import httpx2
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic.alias_generators import to_camel

from ledgerly.agent import AgentServices
from ledgerly.agent.base import (
    AgentEngine,
    AgentEvent,
    AgentRun,
    DoneEvent,
    ErrorEvent,
    LlmUnavailable,
    TokenEvent,
)
from ledgerly.agent.conversations import Conversation, ConversationNotFound
from ledgerly.agent.prompt import user_message
from ledgerly.agent.registry import EngineNotEnabled, choose_engine
from ledgerly.api.deps import CurrentUser, SessionDep, SettingsDep
from ledgerly.api.schemas import AgentBatchRequest, AgentChatRequest
from ledgerly.permissions import Role
from ledgerly.services import batches as batch_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

_bearer = HTTPBearer(auto_error=False)
EngineHeader = Annotated[str | None, Header(alias="X-Agent-Engine", max_length=40)]

def get_agent(request: Request) -> AgentServices:
    agent: AgentServices = request.app.state.agent
    return agent


def get_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> str:
    """The raw login token, passed on to the MCP server so tools run as this user.
    Only used next to CurrentUser, which has already checked it."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return credentials.credentials

AgentDep = Annotated[AgentServices, Depends(get_agent)]
TokenDep = Annotated[str, Depends(get_token)]

def _conversation(agent: AgentServices, conversation_id: str, user_id: str) -> Conversation:
    try:
        return agent.conversations.get(conversation_id, user_id)
    except ConversationNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from None


def _engine(agent: AgentServices, settings: SettingsDep, requested: str | None) -> AgentEngine:
    try:
        return choose_engine(settings, agent.engines, requested)
    except EngineNotEnabled as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None


def _sse(event: AgentEvent) -> str:
    payload = {to_camel(k): v for k, v in dataclasses.asdict(event).items()}
    return f"event: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"

def _known_failure(exc: BaseException) -> str | None:
    """A message for failures the user can fix (model or tool server down), else None.
    The MCP client runs in task groups, so the real error can be inside (nested) ExceptionGroups."""
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            found = _known_failure(inner)
            if found is not None:
                return found
        return None
    if isinstance(exc, LlmUnavailable):
        return str(exc)
    if isinstance(exc, httpx2.TransportError):
        return "The tool server (MCP) is not reachable. Is `python -m ledgerly.mcp_server` running?"
    return None

def _stream(
    agent: AgentServices,
    engine: AgentEngine,
    conversation: Conversation,
    user_id: str,
    token: str,
    start: Callable[[AgentRun], AsyncIterator[AgentEvent]],
    trace: tuple[str, dict[str, Any]],
) -> StreamingResponse:
    """Run the engine and stream its events. `trace` is the LangSmith run name and inputs."""
    trace_name, trace_inputs = trace
    async def events() -> AsyncIterator[str]:
        if conversation.lock.locked():
            yield _sse(ErrorEvent("This conversation is still answering. Wait for it to finish."))
            yield _sse(DoneEvent(conversation.id, engine.name, "error", conversation.pending_batch_id, {}))
            return
        async with conversation.lock:
            run: AgentRun | None = None
            answer: list[str] = []
            metadata = {"engine": engine.name, "conversation_id": conversation.id, "user_id": user_id}
            with agent.tracer.span(
                trace_name, "chain", trace_inputs, tags=[f"engine:{engine.name}"], metadata=metadata
            ) as span:
                try:
                    async with agent.open_toolbox(user_id, token) as toolbox:
                        run = AgentRun(conversation, toolbox, agent.llm, tracer=agent.tracer)
                        async for event in start(run):
                            if isinstance(event, TokenEvent):
                                answer.append(event.text)
                            yield _sse(event)
                except Exception as exc:
                    message = _known_failure(exc)
                    if message is None:
                        logger.exception("Agent run failed (engine=%s, conversation=%s)", engine.name, conversation.id)
                        message = "Something went wrong while answering. Please try again."
                    span.fail(message)
                    yield _sse(ErrorEvent(message))
                    if run is not None:
                        run.stop = "error"
                stop = run.stop if run is not None else "error"
                metrics = run.metrics.summary() if run is not None else {}
                # Metrics as metadata too, so runs can be filtered and compared by engine in LangSmith.
                span.add_tags([f"stop:{stop}"])
                span.add_metadata(metrics)
                span.add_outputs(
                    {
                        "answer": "".join(answer),
                        "stop": stop,
                        "pendingBatchId": conversation.pending_batch_id,
                        "metrics": metrics,
                    }
                )
            yield _sse(DoneEvent(conversation.id, engine.name, stop, conversation.pending_batch_id, metrics))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/chat")
async def chat(
    body: AgentChatRequest,
    user: CurrentUser,
    token: TokenDep,
    agent: AgentDep,
    settings: SettingsDep,
    engine_header: EngineHeader = None,
) -> StreamingResponse:
    engine = _engine(agent, settings, engine_header)
    if body.conversation_id is None:
        conversation = agent.conversations.create(user.id, engine.name)
    else:
        conversation = _conversation(agent, body.conversation_id, user.id)
        if engine_header is not None and conversation.engine != engine.name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This conversation uses the {conversation.engine} engine. Start a new one to switch.",
            )
        engine = _engine(agent, settings, conversation.engine)

    message = user_message(body.message, body.folder_id)
    return _stream(
        agent,
        engine,
        conversation,
        user.id,
        token,
        lambda run: engine.chat(run, message),
        ("agent.chat", {"message": body.message, "folderId": body.folder_id}),
    )


@router.post("/approve")
async def approve(
    body: AgentBatchRequest,
    user: CurrentUser,
    token: TokenDep,
    agent: AgentDep,
    settings: SettingsDep,
    session: SessionDep,
) -> StreamingResponse:
    """Apply the conversation's pending preview. The server looks up the approval code itself,
    as this user; the model never sees it."""
    conversation = _conversation(agent, body.conversation_id, user.id)
    if conversation.pending_batch_id != body.batch_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This batch is not waiting for approval in this conversation."
        )
    batch = batch_service.load_batch(session, user.id, body.batch_id, Role.VIEWER)  # 404 if not visible
    approval_code = batch_service.preview_hash(batch.id, batch.items)
    session.rollback()  # read only; release the connection before streaming

    engine = _engine(agent, settings, conversation.engine)
    return _stream(
        agent,
        engine,
        conversation,
        user.id,
        token,
        lambda run: engine.approve(run, body.batch_id, approval_code),
        ("agent.approve", {"batchId": body.batch_id}),  # never the approval code
    )


@router.post("/undo")
async def undo(body: AgentBatchRequest, user: CurrentUser, token: TokenDep, agent: AgentDep) -> dict[str, Any]:
    """Undo an applied batch. Same rules as everywhere: records edited since are left alone."""
    conversation = _conversation(agent, body.conversation_id, user.id)
    async with agent.open_toolbox(user.id, token) as toolbox:
        outcome = await toolbox.call("undo_batch", {"batch_id": body.batch_id})
    if not outcome.ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=outcome.data.get("error", "Undo failed"))
    
    counts = ", ".join(f"{n} {result.replace('_', ' ')}" for result, n in (outcome.data.get("summary") or {}).items())
    conversation.notes.append(f"The user undid batch {body.batch_id} ({counts}).")
    return outcome.data