"""Concrete LLM providers: mock, OpenAI, Anthropic, Ollama.

Heavy SDKs are imported lazily inside each provider so the app boots even
when a given SDK isn't configured.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx

from app.config import get_settings
from app.llm.base import ChatMessage

settings = get_settings()


class MockProvider:
    """Deterministic offline provider — grounds its answer in retrieved context
    so the RAG flow (and citations) can be demoed without any API key."""

    provider = "mock"

    def __init__(self, model: str = "mock") -> None:
        self.model = model

    def available(self) -> bool:
        return True

    async def stream(
        self, system: str, messages: list[ChatMessage], lang: str = "ru"
    ) -> AsyncIterator[str]:
        question = messages[-1].content if messages else ""
        # Pull the context block the RAG pipeline injected into `system`.
        context = ""
        if "CONTEXT:" in system:
            context = system.split("CONTEXT:", 1)[1].strip()

        first = context.splitlines()[0] if context.splitlines() else ""
        if lang == "en":
            if context:
                reply = (
                    f"Based on your uploaded documents, regarding “{question}”:\n\n"
                    f"{first[:600]}\n\n"
                    "See the sources below for details. "
                    "(Demo mode: connect OpenAI/Anthropic/Ollama for real answers.)"
                )
            else:
                reply = (
                    f"You asked: “{question}”. I couldn't find relevant fragments in the "
                    "uploaded documents. Upload documents or refine your question.\n\n"
                    "(Demo mode, no external model.)"
                )
        else:
            if context:
                reply = (
                    f"На основе загруженных документов по вашему вопросу «{question}»:\n\n"
                    f"{first[:600]}\n\n"
                    "Подробности приведены в источниках ниже. "
                    "(Демо-режим: подключите OpenAI/Anthropic/Ollama для реальных ответов.)"
                )
            else:
                reply = (
                    f"Вы спросили: «{question}». Я не нашёл релевантных фрагментов в "
                    "загруженных документах. Загрузите документы или уточните вопрос.\n\n"
                    "(Демо-режим без внешней модели.)"
                )

        for token in _tokenize(reply):
            await asyncio.sleep(0.012)
            yield token


class OpenAIProvider:
    provider = "openai"

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def available(self) -> bool:
        return bool(settings.openai_api_key)

    async def stream(
        self, system: str, messages: list[ChatMessage], lang: str = "ru"
    ) -> AsyncIterator[str]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        payload = [{"role": "system", "content": system}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]
        stream = await client.chat.completions.create(
            model=self.model, messages=payload, stream=True, temperature=0.2
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class AnthropicProvider:
    provider = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5") -> None:
        self.model = model

    def available(self) -> bool:
        return bool(settings.anthropic_api_key)

    async def stream(
        self, system: str, messages: list[ChatMessage], lang: str = "ru"
    ) -> AsyncIterator[str]:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        payload = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        async with client.messages.stream(
            model=self.model,
            system=system,
            messages=payload,
            max_tokens=1024,
            temperature=0.2,
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OllamaProvider:
    provider = "ollama"

    def __init__(self, model: str = "llama3.1") -> None:
        self.model = model

    def available(self) -> bool:
        """Reachable AND this specific model has been pulled."""
        try:
            r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=1.0)
            if r.status_code != 200:
                return False
            names = {m.get("name", "") for m in r.json().get("models", [])}
            # Ollama tags include an explicit ":latest"; match with or without it.
            return self.model in names or f"{self.model}:latest" in names
        except Exception:
            return False

    async def stream(
        self, system: str, messages: list[ChatMessage], lang: str = "ru"
    ) -> AsyncIterator[str]:
        import json

        payload = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }
        if settings.ollama_num_gpu is not None:
            payload["options"] = {"num_gpu": settings.ollama_num_gpu}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{settings.ollama_base_url}/api/chat", json=payload
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    token = data.get("message", {}).get("content")
                    if token:
                        yield token


def _tokenize(text: str) -> list[str]:
    """Split into word-ish tokens (keeps whitespace) for a natural stream feel."""
    import re

    return re.findall(r"\S+\s*", text) or [text]
