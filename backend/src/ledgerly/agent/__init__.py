"""The in-app agent: two engines (plain loop, LangGraph) behind a feature flag, same model and tools."""

from __future__ import annotations

from dataclasses import dataclass

from ledgerly.agent.base import AgentEngine, LlmClient
from ledgerly.agent.conversations import ConversationStore
from ledgerly.agent.mcp_client import ToolboxFactory

@dataclass
class AgentServices:
    """Everything the agent routes need. create_app builds the real ones; tests pass fakes."""

    engines: dict[str, AgentEngine]
    llm: LlmClient
    open_toolbox: ToolboxFactory
    conversations: ConversationStore