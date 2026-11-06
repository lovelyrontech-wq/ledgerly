"""Shared fixtures. Each test gets its own SQLite file, built by running the real Alembic migrations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.config import BACKEND_DIR, REPO_ROOT
from ledgerly.db.session import make_engine, session_factory

SEED_DIR = REPO_ROOT / "data" / "seed"
TEST_PASSWORD = "test-password-123"


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
