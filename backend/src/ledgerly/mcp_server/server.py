"""The Ledgerly MCP server.

The agent connects over Streamable HTTP and sends the signed-in user's login token
(Authorization: Bearer <token>, the same token the app uses). The server checks the token and
runs every tool as that user, so the agent has exactly the user's permissions, no more.

Run (from backend/):  uv run python -m ledgerly.mcp_server
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.config import Settings
from ledgerly.mcp_server import tools
from ledgerly.security import InvalidTokenError, decode_access_token

INSTRUCTIONS = """\
Ledgerly tools act as the signed-in user, with their folder permissions.
- To change values in bulk, call preview_bulk_update first. It changes nothing.
- Show the preview to the user. Only the user can approve it, in the app. The app then gives you
  an approval code; only then call apply_bulk_update with it. Never guess an approval code.
- Results are per record: records changed since the preview are skipped, not overwritten.
- For how-to questions, call search_help_docs and answer from what it returns.
"""


class LedgerlyTokenVerifier:
    """Accepts the same login tokens the REST API issues."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            user_id = decode_access_token(token, self._secret)
        except InvalidTokenError:
            return None
        return AccessToken(token=token, client_id="ledgerly", scopes=[], subject=user_id)


def user_from_token() -> str:
    """The signed-in user's ID, from the bearer token the HTTP layer already checked."""
    access = get_access_token()
    if access is None or not access.subject:
        raise ToolError("Not signed in.")
    return access.subject


def build_server(
    settings: Settings,
    session_factory: sessionmaker[Session],
    current_user: Callable[[], str] = user_from_token,
) -> MCPServer:
    """Create the server. Tests pass their own `current_user`; in production it comes from the token."""
    secret = settings.auth_secret.get_secret_value() if settings.auth_secret else ""
    server = MCPServer(
        name="ledgerly",
        instructions=INSTRUCTIONS,
        token_verifier=LedgerlyTokenVerifier(secret),
        auth=AuthSettings(
            issuer_url=settings.api_public_url,
            resource_server_url=settings.mcp_public_url,
            validate_token_resource=False,  # our verifier checks the token itself
        ),
    )
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    @server.tool(annotations=read_only)
    def list_folders() -> dict[str, Any]:
        """List the folders the user can access, with their role in each (owner, editor or viewer)."""
        with session_factory() as session:
            return tools.list_folders(session, current_user())

    @server.tool(annotations=read_only)
    def list_records(
        folder_id: Annotated[str, Field(description="Folder ID, e.g. fld_q3_invoices")],
        status: Annotated[str | None, Field(description="Only records with this status, e.g. overdue")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """List records in a folder with their current values."""
        with session_factory() as session:
            return tools.list_records(session, current_user(), folder_id, status, limit, offset)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def preview_bulk_update(
        folder_id: Annotated[str, Field(description="Folder ID")],
        percent: Annotated[
            Decimal, Field(ge=-100, le=1000, decimal_places=2, description="10 means +10%, -5 means -5%")
        ],
        instruction: Annotated[str, Field(min_length=1, max_length=500, description="The user's request, verbatim")],
        status: Annotated[str | None, Field(description="Only change records with this status")] = None,
    ) -> dict[str, Any]:
        """Preview changing every record's value by a percentage. Changes nothing; the user must approve it."""
        with session_factory() as session:
            return tools.preview_bulk_update(
                session,
                current_user(),
                folder_id,
                percent,
                instruction,
                settings.batch_preview_ttl_minutes,
                status,
            )

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True))
    def apply_bulk_update(
        batch_id: Annotated[str, Field(description="The batchId from preview_bulk_update")],
        approval_code: Annotated[
            str, Field(min_length=64, max_length=64, description="The code the app gives when the user approves")
        ],
    ) -> dict[str, Any]:
        """Apply a previewed bulk update the user has approved. Retrying with the same code is safe."""
        with session_factory() as session:
            return tools.apply_bulk_update(session, current_user(), batch_id, approval_code)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def undo_batch(
        batch_id: Annotated[str, Field(description="The batchId of an applied bulk update")],
    ) -> dict[str, Any]:
        """Undo an applied bulk update. Records edited since then are left as they are."""
        with session_factory() as session:
            return tools.undo_batch(session, current_user(), batch_id)

    @server.tool(annotations=read_only)
    def search_help_docs(
        query: Annotated[str, Field(min_length=1, max_length=300)],
        limit: Annotated[int, Field(ge=1, le=5)] = 3,
    ) -> dict[str, Any]:
        """Search Ledgerly's help articles. Use for how-to questions."""
        current_user()  # signed-in users only
        return tools.search_help_docs(settings.data_dir / "help-docs", query, limit)

    return server