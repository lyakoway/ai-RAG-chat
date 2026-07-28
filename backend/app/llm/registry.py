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
    ZaiProvider,
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
    ModelSpec("zai:glm-4.5-flash", "zai", "glm-4.5-flash", "GLM-4.5 Flash (Z.ai, бесплатно)",
              "Бесплатная модель Zhipu GLM через Z.ai (без VPN)", ZaiProvider),
    ModelSpec("zai:glm-4.6", "zai", "glm-4.6", "GLM-4.6 (Z.ai)",
              "Платная, более мощная GLM через Z.ai", ZaiProvider),
    ModelSpec("ollama:llama3.2:3b", "ollama", "llama3.2:3b", "Llama 3.2 3B (local)",
              "Локальная модель через Ollama (быстрая)", OllamaProvider),
    ModelSpec("ollama:llama3.1", "ollama", "llama3.1", "Llama 3.1 8B (local)",
              "Локальная модель через Ollama", OllamaProvider),
    ModelSpec("ollama:mistral", "ollama", "mistral", "Mistral (local)",
              "Локальная модель через Ollama", OllamaProvider),
]

_BY_ID = {s.id: s for s in _SPECS}


def _build(spec: ModelSpec) -> LLMProvider:
    return spec.factory(spec.model)


def list_models() -> list[dict]:
    out = []
    # Availability depends on the specific model for Ollama (is it pulled?),
    # but only on the provider for key-based ones (OpenAI/Anthropic/mock).
    avail_cache: dict[str, bool] = {}
    for spec in _SPECS:
        key = spec.id if spec.provider == "ollama" else spec.provider
        if key not in avail_cache:
            avail_cache[key] = _build(spec).available()
        out.append({
            "id": spec.id,
            "provider": spec.provider,
            "label": spec.label,
            "available": avail_cache[key],
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
