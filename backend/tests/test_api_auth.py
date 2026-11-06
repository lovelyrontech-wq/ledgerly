"""Login, tokens, and the startup secret check."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from ledgerly.api.app import create_app
from ledgerly.config import Settings
from ledgerly.security import create_access_token
from tests.conftest import TEST_PASSWORD, TEST_SECRET

Headers = Callable[[str], dict[str, str]]


def test_login_returns_token_and_user(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"email": "alice@ledgerly.test", "password": TEST_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == 3600
    assert body["user"] == {"id": "usr_alice", "email": "alice@ledgerly.test", "name": "Alice Owner"}


def test_login_email_is_case_and_space_insensitive(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"email": "  Alice@Ledgerly.TEST ", "password": TEST_PASSWORD})
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("alice@ledgerly.test", "wrong-password"),
        ("nobody@ledgerly.test", TEST_PASSWORD),
    ],
)
def test_bad_login_gives_same_error(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong email or password"}


def test_me_returns_signed_in_user(client: TestClient, auth_headers: Headers) -> None:
    response = client.get("/api/auth/me", headers=auth_headers("bob"))
    assert response.json()["id"] == "usr_bob"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ],
)
def test_missing_or_bad_token_is_401(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_token_is_401(client: TestClient) -> None:
    token = create_access_token("usr_alice", TEST_SECRET, ttl_minutes=5, now=datetime.now(UTC) - timedelta(hours=1))
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_signed_with_other_secret_is_401(client: TestClient) -> None:
    token = create_access_token("usr_alice", "another-secret-" + "y" * 32, ttl_minutes=5)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_for_deleted_user_is_401(client: TestClient) -> None:
    token = create_access_token("usr_deleted", TEST_SECRET, ttl_minutes=5)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("secret", [None, "too-short"])
def test_app_refuses_to_start_without_strong_secret(secret: str | None) -> None:
    settings = Settings(auth_secret=SecretStr(secret) if secret else None)
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        create_app(settings=settings)
