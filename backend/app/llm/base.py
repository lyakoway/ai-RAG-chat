"""LLM provider abstraction.

Every provider streams string chunks given a system prompt and a list of
chat messages. This keeps the RAG pipeline provider-agnostic.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str


class LLMProvider(Protocol):
    provider: str
    model: str

    def available(self) -> bool:
        """Whether this provider is usable (key present / reachable)."""
        ...

    async def stream(
        self, system: str, messages: list[ChatMessage], lang: str = "ru"
    ) -> AsyncIterator[str]:
        """Yield response text chunks. `lang` is the UI language ("ru"|"en")."""
        ...
