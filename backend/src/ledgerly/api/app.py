"""Create the FastAPI app.

Run (from backend/):  uv run uvicorn ledgerly.api.app:create_app --factory --reload
API docs:             http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.agent import AgentServices
from ledgerly.agent.conversations import ConversationStore
from ledgerly.agent.llm import OllamaLlm
from ledgerly.agent.mcp_client import http_toolbox_factory
from ledgerly.agent.registry import build_engines
from ledgerly.api.routes import agent, auth, batches, folders, records

from ledgerly.config import Settings, get_settings
from ledgerly.db.session import session_factory as default_session_factory
from ledgerly.permissions import FolderNotFound, PermissionDenied
from ledgerly.security import MIN_SECRET_LENGTH

# 2. add an import under "from ledgerly.security import MIN_SECRET_LENGTH":
from ledgerly.services.batches import BatchConflict, BatchNotFound


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    agent_services: AgentServices | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    secret = settings.auth_secret.get_secret_value() if settings.auth_secret else ""
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"AUTH_SECRET must be set in backend/.env and be at least {MIN_SECRET_LENGTH} characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )

    app = FastAPI(title="Ledgerly API", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = session_factory or default_session_factory()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key",  "X-Agent-Engine"],
    )

    app.state.agent = agent_services or AgentServices(
        engines=build_engines(settings),  # fails here if the AGENT_ENGINE flags are wrong
        llm=OllamaLlm(settings),
        open_toolbox=http_toolbox_factory(settings.mcp_public_url),
        conversations=ConversationStore(settings.agent_max_conversations),
    )

    @app.exception_handler(FolderNotFound)
    def _folder_not_found(_: Request, __: FolderNotFound) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Folder not found"})

    @app.exception_handler(PermissionDenied)
    def _permission_denied(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": f"You need {exc.required.label} access to do this (you are {exc.actual.label})"},
        )

    # 3. add these handlers next to the other two exception handlers:
    @app.exception_handler(BatchNotFound)
    def _batch_not_found(_: Request, __: BatchNotFound) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Batch not found"})

    @app.exception_handler(BatchConflict)
    def _batch_conflict(_: Request, exc: BatchConflict) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(folders.router)
    app.include_router(records.router)
    app.include_router(batches.router)
    app.include_router(agent.router)
    return app
