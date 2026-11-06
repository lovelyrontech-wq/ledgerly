"""Login and current user."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from ledgerly.api.deps import CurrentUser,SettingsDep, SessionDep
from ledgerly.api.schemas import LoginRequest, LoginResponse, UserOut
from ledgerly.db.models import User
from ledgerly.security import create_access_token, verify_password


router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, session: SessionDep, settings:SettingsDep) -> LoginResponse:
    email = body.email.strip().lower()
    user = session.scalar(select(User).where(func.lower(User.email) == email))

    #Same error and same work for no such user and wrong passowrd
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail= "Wrong email or password")

    assert settings.auth_secret is not None
    token = create_access_token(user.id, settings.auth_secret.get_secret_value(), settings.auth_token_ttl_minutes)
    return LoginResponse(
        access_token=token,
        expires_in=settings.auth_token_ttl_minutes * 60,
        user=UserOut.model_validate(user)
    )

@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)

