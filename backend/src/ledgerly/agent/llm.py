"""The model: Ollama, streamed, with tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import ollama

from ledgerly.agent.base import LlmChunk, LlmStats, LlmToolCall, LlmUnavailable
from ledgerly.config import Settings

class OllamaLlm:
    def __init__(self, settings: Settings, client: ollama.AsyncClient | None = None) -> None:
        self._client = client or ollama.AsyncClient(host=settings.ollama_base_url)
        self._model = settings.ollama_chat_model
        self._keep_alive = settings.ollama_keep_alive
        self._think = settings.agent_think
        self._options = {
            "temperature": settings.agent_temperature,
            "seed": settings.agent_seed,
            "num_ctx": settings.ollama_num_ctx,
        }

    async def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[LlmChunk]:
        try:
            stream = await self._client.chat(
                model=self._model,
                messages=messages,
                tools=tools,
                stream=True,
                think=self._think,
                options=self._options,
                keep_alive=self._keep_alive,
            )
            async for part in stream:
                calls = [
                    LlmToolCall(call.function.name, dict(call.function.arguments or {}))
                    for call in part.message.tool_calls or []
                ]
                stats = None
                if part.done:
                    stats = LlmStats(
                        prompt_tokens=part.prompt_eval_count or 0,
                        output_tokens=part.eval_count or 0,
                        model_ms=(part.total_duration or 0) / 1_000_000,
                    )
                yield LlmChunk(text=part.message.content or "", tool_calls=calls, stats=stats)
        except ollama.ResponseError as exc:
            raise LlmUnavailable(f"The model returned an error: {exc.error}") from exc
        except (ConnectionError, httpx.HTTPError) as exc:
            raise LlmUnavailable("The model server (Ollama) is not reachable. Is `ollama serve` running?") from exc