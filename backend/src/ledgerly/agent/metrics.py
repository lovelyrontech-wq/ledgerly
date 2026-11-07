"""Speed numbers for one agent run, measured the same way for every engine.

framework overhead = total - time in the model - time in tools. That is the part the engine
itself (plain loop or LangGraph) adds, and the number the speed demo compares.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ledgerly.agent.base import LlmStats

def _now_ms() -> float:
    return time.perf_counter() * 1000

@dataclass
class RunMetrics:
    started_ms: float = field(default_factory=_now_ms)
    first_token_ms: float | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    model_ms: float = 0.0  # as reported by the model server
    llm_wall_ms: float = 0.0  # measured here: model time + network + streaming
    tool_ms: float = 0.0
    _llm_started_ms: float | None = None

    def llm_started(self) -> None:
        self.llm_calls += 1
        self._llm_started_ms = _now_ms()

    def first_token(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = _now_ms()

    def llm_finished(self, stats: LlmStats | None) -> None:
        if self._llm_started_ms is not None:
            self.llm_wall_ms += _now_ms() - self._llm_started_ms
            self._llm_started_ms = None
        if stats is not None:
            self.prompt_tokens += stats.prompt_tokens
            self.output_tokens += stats.output_tokens
            self.model_ms += stats.model_ms

    def tool_finished(self, duration_ms: float) -> None:
        self.tool_calls += 1
        self.tool_ms += duration_ms

    def summary(self) -> dict[str, Any]:
        total = _now_ms() - self.started_ms
        ttft = None if self.first_token_ms is None else round(self.first_token_ms - self.started_ms, 1)
        return {
            "totalMs": round(total, 1),
            "timeToFirstTokenMs": ttft,
            "llmCalls": self.llm_calls,
            "toolCalls": self.tool_calls,
            "promptTokens": self.prompt_tokens,
            "outputTokens": self.output_tokens,
            "modelMs": round(self.model_ms, 1),
            "llmWallMs": round(self.llm_wall_ms, 1),
            "toolMs": round(self.tool_ms, 1),
            # Measured with wall-clock LLM time, so network/streaming is not counted as engine overhead.
            "overheadMs": round(max(total - self.llm_wall_ms - self.tool_ms, 0.0), 1),
        }