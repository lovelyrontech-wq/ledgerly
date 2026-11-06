"""Start the MCP server: uv run python -m ledgerly.mcp_server"""

from __future__ import annotations

from ledgerly.config import get_settings
from ledgerly.db.session import session_factory
from ledgerly.mcp_server.server import build_server
from ledgerly.security import MIN_SECRET_LENGTH


def main() -> None:
    settings = get_settings()
    secret = settings.auth_secret.get_secret_value() if settings.auth_secret else ""
    if len(secret) < MIN_SECRET_LENGTH:
        raise SystemExit(f"AUTH_SECRET must be set in backend/.env (at least {MIN_SECRET_LENGTH} characters).")
    server = build_server(settings, session_factory())
    server.run("streamable-http", host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
