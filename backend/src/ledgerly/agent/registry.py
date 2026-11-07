"""The feature flag: which agent engines exist, which are enabled, and which one a request uses.

AGENT_ENGINE           the default engine
AGENT_ENGINES_ENABLED  engines a request may choose with the X-Agent-Engine header
"""

from __future__ import annotations

from collections.abc import Callable

from ledgerly.agent.base import AgentEngine
from ledgerly.agent.engines.plain import PlainEngine
from ledgerly.config import Settings

class EngineNotEnabled(Exception):
    pass


def _plain(settings: Settings) -> AgentEngine:
    return PlainEngine(max_steps=settings.agent_max_steps)


def _langgraph(settings: Settings) -> AgentEngine:
    try:
        from ledgerly.agent.engines.langgraph import LangGraphEngine
    except ImportError as exc:  # the optional extra is not installed
        raise RuntimeError(
            "The langgraph engine is enabled but LangGraph is not installed. Run: uv sync --extra langgraph"
        ) from exc
    return LangGraphEngine(settings.resolved_checkpoint_db, max_steps=settings.agent_max_steps)


# name -> builder. Builders import their engine only when it is enabled.
KNOWN_ENGINES: dict[str, Callable[[Settings], AgentEngine]] = {"plain": _plain, "langgraph": _langgraph}

def build_engines(settings: Settings) -> dict[str, AgentEngine]:
    """Build every enabled engine. Called at startup, so a bad flag stops the app right away."""
    enabled = settings.agent_engines_enabled
    unknown = [name for name in enabled if name not in KNOWN_ENGINES]
    if unknown:
        raise RuntimeError(f"AGENT_ENGINES_ENABLED has unknown engines {unknown}. Known: {sorted(KNOWN_ENGINES)}")
    if settings.agent_engine not in enabled:
        raise RuntimeError(f"AGENT_ENGINE={settings.agent_engine!r} must be one of AGENT_ENGINES_ENABLED={enabled}")
    return {name: KNOWN_ENGINES[name](settings) for name in enabled}

def choose_engine(settings: Settings, engines: dict[str, AgentEngine], requested: str | None) -> AgentEngine:
    name = (requested or settings.agent_engine).strip().lower()
    if name not in engines:
        raise EngineNotEnabled(f"Agent engine {name!r} is not enabled. Enabled: {sorted(engines)}")
    return engines[name]