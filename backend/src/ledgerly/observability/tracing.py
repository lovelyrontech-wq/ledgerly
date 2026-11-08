"""LangSmith tracing for the agent (step 7).

One trace per agent request (chat or approve), tagged `engine:plain` or `engine:langgraph`, with a
child run for every model call and every tool call, and the speed metrics on the trace. With the
LangGraph engine, LangGraph's own graph and node runs appear inside the same trace.

Off unless LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set. Tracing must never break a chat:
the langsmith client sends runs from a background thread and only logs failures.

Never traced: the approval code (redacted from tool arguments) and the user's login token.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from langsmith import Client

    from ledgerly.config import Settings

logger = logging.getLogger(__name__)

RunType = Literal["chain", "llm", "tool"]

# Tool arguments that must never leave the server.
SECRET_ARGUMENTS = frozenset({"approval_code"})
REDACTED = "[redacted]"


def redact(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {key: REDACTED if key in SECRET_ARGUMENTS else value for key, value in arguments.items()}


class Span(Protocol):
    """What the agent code can do with an open run."""

    def add_outputs(self, outputs: dict[str, Any]) -> None: ...
    def add_tags(self, tags: Sequence[str]) -> None: ...
    def add_metadata(self, metadata: dict[str, Any]) -> None: ...
    def fail(self, message: str) -> None: ...


class _NoopSpan:
    def add_outputs(self, outputs: dict[str, Any]) -> None:
        pass

    def add_tags(self, tags: Sequence[str]) -> None:
        pass

    def add_metadata(self, metadata: dict[str, Any]) -> None:
        pass

    def fail(self, message: str) -> None:
        pass


NOOP_SPAN: Span = _NoopSpan()


class _LangSmithSpan:
    def __init__(self, run: Any) -> None:  # langsmith.RunTree
        self._run = run
        self.error: str | None = None

    def add_outputs(self, outputs: dict[str, Any]) -> None:
        self._run.add_outputs(outputs)

    def add_tags(self, tags: Sequence[str]) -> None:
        self._run.add_tags(list(tags))

    def add_metadata(self, metadata: dict[str, Any]) -> None:
        self._run.add_metadata(metadata)

    def fail(self, message: str) -> None:
        self.error = message


class Tracer:
    """Opens LangSmith runs. Disabled (every span a no-op) when tracing is off."""

    def __init__(self, client: Client | None = None, project: str = "ledgerly-dev") -> None:
        self._client = client
        self.project = project

    @classmethod
    def disabled(cls) -> Tracer:
        return cls(None)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def span(
        self,
        name: str,
        run_type: RunType,
        inputs: dict[str, Any],
        *,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> Generator[Span]:
        """A run around the block. Nested spans become its children (via context variables, so
        this also works across `await` and inside LangGraph's tasks)."""
        if self._client is None:
            yield NOOP_SPAN
            return

        from langsmith import trace, tracing_context

        # tracing_context first: langsmith only sends a run if tracing was on when it started.
        with (
            tracing_context(enabled=True, client=self._client, project_name=self.project),
            trace(
                name,
                run_type,
                inputs=inputs,
                tags=list(tags),
                metadata=dict(metadata or {}),
                client=self._client,
                project_name=self.project,
            ) as run,
        ):
            span = _LangSmithSpan(run)
            yield span
            run.end(error=span.error)

    def flush(self) -> None:
        """Send what is still queued. Called on shutdown."""
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception:  # never fail shutdown because of tracing
            logger.warning("Could not flush LangSmith traces", exc_info=True)


def build_tracer(settings: Settings) -> Tracer:
    if not settings.langsmith_tracing:
        return Tracer.disabled()
    api_key = settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else ""
    if not api_key:
        logger.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty: tracing stays off.")
        return Tracer.disabled()

    from langsmith import Client

    client = Client(api_url=settings.langsmith_endpoint, api_key=api_key)
    logger.info("LangSmith tracing on (project %s)", settings.langsmith_project)
    return Tracer(client, settings.langsmith_project)
