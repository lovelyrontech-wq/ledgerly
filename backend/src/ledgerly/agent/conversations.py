"""Chat history, kept in memory per API process (lost on restart; fine for the demo).

Each conversation belongs to one user and one engine. Another user's conversation looks the
same as a missing one, so IDs reveal nothing.
"""
from __future__ import annotations

import asyncio
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# Messages kept per conversation (besides the system prompt). Older ones are dropped.
MAX_HISTORY_MESSAGES = 40


class ConversationNotFound(Exception):
    pass

@dataclass
class Conversation:
    id: str
    user_id: str
    engine: str
    messages: list[dict[str, Any]] = field(default_factory=list)  # without the system prompt
    pending_batch_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one request at a time

    def add(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if len(self.messages) > MAX_HISTORY_MESSAGES:
            # Cut at a user message, so the history never starts with a dangling tool result.
            cut = len(self.messages) - MAX_HISTORY_MESSAGES
            while cut < len(self.messages) and self.messages[cut]["role"] != "user":
                cut += 1
            del self.messages[:cut]


class ConversationStore:
    def __init__(self, max_conversations: int = 500) -> None:
        self._items: OrderedDict[str, Conversation] = OrderedDict()
        self._max = max_conversations

    def create(self, user_id: str, engine: str) -> Conversation:
        conversation = Conversation(id=f"conv_{secrets.token_urlsafe(12)}", user_id=user_id, engine=engine)
        self._items[conversation.id] = conversation
        while len(self._items) > self._max:
            self._items.popitem(last=False)
        return conversation

    def get(self, conversation_id: str, user_id: str) -> Conversation:
        conversation = self._items.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ConversationNotFound(conversation_id)
        self._items.move_to_end(conversation_id)
        return conversation