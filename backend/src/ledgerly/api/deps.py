"""FastAPI dependencies: database session, settings, and the signed-in user."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ledgerly.config import Settings
from ledgerly.db.models import User
from ledgerly.security import InvalidTokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. Routes commit explicitly; anything not committed is rolled back."""
    with request.app.state.session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not signed in")
    assert settings.auth_secret is not None  # checked at startup in craete_app
    try:
        user_id = decode_access_token(credentials.credentials, settings.auth_secret.get_secret_value())
    except InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    user = session.get(User, user_id)

    if user is None:
        # Token is valid but the user was deleted
        raise _unauthorized("Invalid or Expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
