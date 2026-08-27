"""Vector search endpoint.

Direct semantic search over document chunks — the same retrieval the RAG
pipeline uses (fastembed embeddings → Chroma cosine ANN), but without the
LLM step. Returns ranked fragments with similarity scores so the UI can show
them and open the source document.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import vectorstore
from app.core.embeddings import active_model_name
from app.db.session import get_db
from app.schemas.dto import SearchResponse, Source

router = APIRouter(prefix="/api/search", tags=["search"])
settings = get_settings()

_TOP_K_MIN, _TOP_K_MAX = 1, 50


@router.get("", response_model=SearchResponse)
def vector_search(
    q: str = Query(..., min_length=1, description="Поисковый запрос"),
    category: str | None = Query(None, description="Фильтр по категории"),
    document_ids: str | None = Query(
        None, description="CSV списка id документов (опционально)"
    ),
    top_k: int | None = Query(None, ge=_TOP_K_MIN, le=_TOP_K_MAX),
    db: Session = Depends(get_db),
) -> SearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(400, "Пустой поисковый запрос")

    ids = [s for s in (document_ids or "").split(",") if s.strip()]

    started = time.perf_counter()
    hits = vectorstore.query(
        text=query,
        top_k=top_k or settings.retrieval_top_k,
        category=category,
        document_ids=ids or None,
    )
    took_ms = round((time.perf_counter() - started) * 1000)

    results: list[Source] = []
    for h in hits:
        snippet = h["text"].strip().replace("\n", " ")
        if len(snippet) > 600:
            snippet = snippet[:600].rstrip() + "…"
        results.append(
            Source(
                document_id=h["document_id"],
                filename=h["filename"],
                page=h.get("page"),
                snippet=snippet,
                score=h.get("score"),
                chunk_index=h.get("chunk_index"),
            )
        )

    return SearchResponse(
        query=query,
        took_ms=took_ms,
        embedding_model=active_model_name(),
        results=results,
    )
