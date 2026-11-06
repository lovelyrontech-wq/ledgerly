"""Settings loaded from environment variables and backend/.env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5:7b-instruct"
    ollama_embed_model: str = "nomic-embed-text"

    @property
    def resolved_database_url(self) -> str:
        """Relative SQLite paths are resolved against backend/, so the DB file is the same
        no matter which directory a command runs from."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            path = self.database_url[len(prefix):]
            if path and path != ":memory:" and not Path(path).is_absolute():
                return f"{prefix}{(BACKEND_DIR / path).as_posix()}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
