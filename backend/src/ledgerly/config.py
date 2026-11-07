"""Settings loaded from environment variables and backend/.env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from typing import Annotated


BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///dev.db"
    seed_demo_password: SecretStr | None = None
    data_dir: Path = REPO_ROOT / "data"

    # Signs login tokens. Required to run the API. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"

    auth_secret: SecretStr | None = None
    auth_token_ttl_minutes: int = 480

    # Browser origins allowed to call the API (the Next.js dev server).
    cors_origins: list[str] = ["http://localhost:3000"]

    # How long a bulk-update preview can be approved before it expires.
    batch_preview_ttl_minutes: int = 15

    # MCP server (the agent's tools). Public URLs are what clients use to reach each service.
    api_public_url: str = "http://localhost:8000"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001
    mcp_public_url: str = "http://localhost:8001/mcp"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5:7b-instruct"
    ollama_embed_model: str = "nomic-embed-text"

        # How long Ollama keeps the model loaded after a request ("30m", "-1" = forever).
    ollama_keep_alive: str = "30m"
    # Context window in tokens. Ollama's default (4096) is too small for tool schemas + history.
    ollama_num_ctx: int = 8192

    # Agent (step 5). AGENT_ENGINE is the default; AGENT_ENGINES_ENABLED lists the engines a request
    # may pick with the X-Agent-Engine header. Comma-separated in .env: plain,langgraph
    agent_engine: str = "plain"
    agent_engines_enabled: Annotated[list[str], NoDecode] = ["plain"]
    agent_max_steps: int = 6  # model calls per user message, so a confused model cannot loop forever
    agent_temperature: float = 0.0
    agent_seed: int = 42  # with temperature 0, makes runs repeatable for the benchmark
    agent_think: bool = False  # reasoning models (qwen3) think before answering; off is much faster
    agent_max_conversations: int = 500  # kept in memory; the oldest is dropped first

    @property
    def resolved_database_url(self) -> str:
        """Relative SQLite paths are resolved against backend/, so the DB file is the same
        no matter which directory a command runs from."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            path = self.database_url[len(prefix) :]
            if path and path != ":memory:" and not Path(path).is_absolute():
                return f"{prefix}{(BACKEND_DIR / path).as_posix()}"
        return self.database_url

    @field_validator("agent_engines_enabled", mode="before")
    @classmethod
    def _split_engines(cls, value: object) -> object:
        if isinstance(value, str):
            return [name.strip() for name in value.split(",") if name.strip()]
        return value

@lru_cache
def get_settings() -> Settings:
    return Settings()
