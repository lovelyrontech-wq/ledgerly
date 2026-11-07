"""Text embeddings from Ollama (nomic-embed-text by default)."""

from __future__ import annotations

from typing import Protocol

import httpx
import ollama

from ledgerly.config import Settings


class EmbeddingUnavailable(Exception):
    """The embedding model could not be reached or failed."""


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in the same order. Raises EmbeddingUnavailable."""
        ...


class OllamaEmbedder:
    def __init__(self, settings: Settings, client: ollama.AsyncClient | None = None) -> None:
        # Embedding a query is quick, so fail fast and fall back to keyword search.
        self._client = client or ollama.AsyncClient(host=settings.ollama_base_url, timeout=30)
        self.model = settings.ollama_embed_model
        self._keep_alive = settings.ollama_keep_alive
    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.embed(model=self.model, input=texts, keep_alive=self._keep_alive)
        except ollama.ResponseError as exc:
            raise EmbeddingUnavailable(f"The embedding model returned an error: {exc.error}") from exc
        except (ConnectionError, httpx.HTTPError) as exc:
            raise EmbeddingUnavailable("Ollama is not reachable for embeddings.") from exc
        vectors = [list(v) for v in response.embeddings]
        if len(vectors) != len(texts):
            raise EmbeddingUnavailable(f"Expected {len(texts)} embeddings, got {len(vectors)}.")
        return vectors