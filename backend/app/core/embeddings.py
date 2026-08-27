"""Embedding abstraction.

Default: local ONNX multilingual model via fastembed (no API key, works
offline, handles RU/EN). Optional: OpenAI embeddings when configured.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings

settings = get_settings()


class LocalEmbeddings:
    """fastembed-based local embeddings (lazy model download on first use)."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class OpenAIEmbeddings:
    def __init__(self, model_name: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


@lru_cache
def get_embeddings():
    if settings.embedding_provider == "openai" and settings.openai_api_key:
        return OpenAIEmbeddings(settings.openai_embedding_model)
    # fastembed uses its own short model aliases; map the HF name if needed.
    model = _resolve_local_model(settings.local_embedding_model)
    return LocalEmbeddings(model)


def active_model_name() -> str:
    """Human-readable id of the embedding model currently in use."""
    if settings.embedding_provider == "openai" and settings.openai_api_key:
        return settings.openai_embedding_model
    return _resolve_local_model(settings.local_embedding_model)


def _resolve_local_model(name: str) -> str:
    # fastembed ships this multilingual model under this exact id.
    known_multilingual = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    return known_multilingual if "multilingual" in name else name
