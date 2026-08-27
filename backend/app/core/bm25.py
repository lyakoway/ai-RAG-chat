"""Lexical BM25 search over the Chroma collection.

Hybrid retrieval = BM25 (exact terms, numbers, product names) + vector search
(semantic similarity), fused with Reciprocal Rank Fusion. The BM25 index is
built lazily from all indexed chunks and rebuilt when the collection size
changes — plenty for a demo-scale corpus, no extra storage.
"""
from __future__ import annotations

import re
from functools import lru_cache

from app.config import get_settings

settings = get_settings()

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _collection_snapshot() -> tuple[int, list[str], list[dict]]:
    from app.core.vectorstore import _collection

    data = _collection().get(include=["documents", "metadatas"])
    count = len(data.get("documents") or [])
    return count, data.get("documents") or [], data.get("metadatas") or []


@lru_cache
def _index_for_count(count: int):
    """BM25 index cached by collection size; a new/removed chunk rebuilds it."""
    from rank_bm25 import BM25Okapi

    _, docs, _ = _collection_snapshot()
    if not docs:
        return None, []
    corpus = [tokenize(d) for d in docs]
    return BM25Okapi(corpus), docs


def bm25_search(
    *, text: str, top_k: int, category: str | None = None, document_ids: list[str] | None = None
) -> dict[str, float]:
    """Returns {chunk_id: bm25_score} for the top-k lexical matches."""
    from app.core.vectorstore import _collection

    bm25, docs = _index_for_count(_collection_snapshot()[0])
    if bm25 is None or not text.strip():
        return {}

    scores = bm25.get_scores(tokenize(text))
    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[: top_k * 3]

    ids = _collection().get(include=[]).get("ids") or []
    out: dict[str, float] = {}
    for i in order:
        if scores[i] <= 0:
            continue
        chunk_id = ids[i]
        if not _passes_filter(chunk_id, category, document_ids):
            continue
        out[chunk_id] = float(scores[i])
        if len(out) >= top_k:
            break
    return out


def _passes_filter(chunk_id: str, category: str | None, document_ids: list[str] | None) -> bool:
    from app.core.vectorstore import _collection

    meta = (_collection().get(ids=[chunk_id], include=["metadatas"]).get("metadatas") or [{}])[0]
    if category and category != "All" and meta.get("category") != category:
        return False
    if document_ids and meta.get("document_id") not in document_ids:
        return False
    return True


def rrf_fuse(rankings: list[dict[str, float]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: score = Σ 1/(k + rank_i). Input: {id: score}."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(
            sorted(ranking, key=lambda i: ranking[i], reverse=True), start=1
        ):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return fused
