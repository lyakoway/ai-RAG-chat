"""Cross-encoder reranking via fastembed (local ONNX, no API key).

Two-stage retrieval: a fast first-stage (vectors / hybrid) pulls a candidate
pool, then the cross-encoder scores each (query, chunk) pair and the top-k is
cut from the reranked list. The model is multilingual (bge-reranker-base) and
loads lazily — first call downloads ~1 GB, so reranking is opt-in.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings

settings = get_settings()


@lru_cache
def _model():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=settings.rerank_model)


def rerank(query: str, candidates: list[dict], text_key: str = "text") -> list[dict]:
    """Sorts candidates by cross-encoder relevance; keeps the original dicts."""
    if len(candidates) <= 1:
        return candidates
    scores = list(_model().rerank(query, [c[text_key] for c in candidates]))
    ranked = sorted(zip(candidates, scores), key=lambda cs: cs[1], reverse=True)
    return [c for c, _ in ranked]
