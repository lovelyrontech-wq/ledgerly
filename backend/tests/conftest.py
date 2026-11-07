"""Shared fixtures. Each test gets its own SQLite file, built by running the real Alembic migrations."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.api.app import create_app
from ledgerly.config import BACKEND_DIR, REPO_ROOT, Settings
from ledgerly.db.seed import seed
from ledgerly.db.session import make_engine, session_factory

SEED_DIR = REPO_ROOT / "data" / "seed"
TEST_PASSWORD = "test-password-123"
TEST_SECRET = "test-secret-" + "x" * 32


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")

    eng = make_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def make_session(engine: Engine) -> sessionmaker[Session]:
    return session_factory(engine)


@pytest.fixture
def seeded(make_session: sessionmaker[Session]) -> sessionmaker[Session]:
    """A database loaded with the sample data."""
    with make_session.begin() as session:
        seed(session, SEED_DIR, TEST_PASSWORD)
    return make_session


@pytest.fixture
def settings() -> Settings:
    # bm25: tests never call Ollama. Hybrid search has its own tests with a fake embedder.
    return Settings(auth_secret=SecretStr(TEST_SECRET), auth_token_ttl_minutes=60, help_search_mode="bm25")

@pytest.fixture
def client(seeded: sessionmaker[Session], settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings=settings, session_factory=seeded)) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> Callable[[str], dict[str, str]]:
    """auth_headers("alice") -> {"Authorization": "Bearer <token>"}"""
    cache: dict[str, dict[str, str]] = {}

    def _headers(user: str) -> dict[str, str]:
        if user not in cache:
            response = client.post(
                "/api/auth/login", json={"email": f"{user}@ledgerly.test", "password": TEST_PASSWORD}
            )
            assert response.status_code == 200, response.text
            cache[user] = {"Authorization": f"Bearer {response.json()['accessToken']}"}
        return cache[user]

    return _headers
