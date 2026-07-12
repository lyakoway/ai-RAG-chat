"""Registry of selectable models across all providers.

The UI shows this list; unavailable models (missing key / offline) are marked
so the user understands why they can't be selected.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import LLMProvider
from app.llm.providers import (
    AnthropicProvider,
    MockProvider,
    OllamaProvider,
    OpenAIProvider,
)


@dataclass
class ModelSpec:
    id: str
    provider: str
    model: str
    label: str
    description: str
    factory: type


# Order matters: first entry is the safe default (always available).
_SPECS: list[ModelSpec] = [
    ModelSpec("mock", "mock", "mock", "Demo (offline)",
              "Детерминированный демо-режим без ключей", MockProvider),
    ModelSpec("openai:gpt-4o-mini", "openai", "gpt-4o-mini", "GPT-4o mini",
              "Быстрая и дешёвая модель OpenAI", OpenAIProvider),
    ModelSpec("openai:gpt-4o", "openai", "gpt-4o", "GPT-4o",
              "Флагманская модель OpenAI", OpenAIProvider),
    ModelSpec("anthropic:claude-sonnet-5", "anthropic", "claude-sonnet-5", "Claude Sonnet 5",
              "Сбалансированная модель Anthropic", AnthropicProvider),
    ModelSpec("anthropic:claude-opus-4-8", "anthropic", "claude-opus-4-8", "Claude Opus 4.8",
              "Самая мощная модель Anthropic", AnthropicProvider),
    ModelSpec("ollama:llama3.1", "ollama", "llama3.1", "Llama 3.1 (local)",
              "Локальная модель через Ollama", OllamaProvider),
    ModelSpec("ollama:mistral", "ollama", "mistral", "Mistral (local)",
              "Локальная модель через Ollama", OllamaProvider),
]

_BY_ID = {s.id: s for s in _SPECS}


def _build(spec: ModelSpec) -> LLMProvider:
    return spec.factory(spec.model)


def list_models() -> list[dict]:
    out = []
    # Cache availability per provider to avoid repeated network probes.
    avail_cache: dict[str, bool] = {}
    for spec in _SPECS:
        if spec.provider not in avail_cache:
            avail_cache[spec.provider] = _build(spec).available()
        out.append({
            "id": spec.id,
            "provider": spec.provider,
            "label": spec.label,
            "available": avail_cache[spec.provider],
            "description": spec.description,
        })
    return out


def get_provider(model_id: str) -> LLMProvider:
    """Resolve a model id to a provider instance, falling back to mock."""
    spec = _BY_ID.get(model_id)
    if spec is None:
        return MockProvider()
    provider = _build(spec)
    if not provider.available():
        # Graceful degradation: keep the app usable in a portfolio demo.
        return MockProvider()
    return provider
