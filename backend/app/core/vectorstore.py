"""ChromaDB wrapper.

One persistent collection holds all chunks. Each chunk stores metadata
(document_id, filename, category, page, label, chunk_index) so retrieval can
filter by category/document and return citation info. We pass our own
embeddings (Chroma's default embedder is disabled) to keep control of the
model used for both indexing and querying.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.core.chunking import Chunk
from app.core.embeddings import get_embeddings

settings = get_settings()

COLLECTION = "documents"


@lru_cache
def _client():
    import chromadb

    return chromadb.PersistentClient(path=str(settings.chroma_dir))


@lru_cache
def _collection():
    # embedding_function=None -> we always supply embeddings explicitly.
    return _client().get_or_create_collection(
        name=COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def add_document_chunks(
    *, document_id: str, filename: str, category: str, chunks: list[Chunk]
) -> None:
    if not chunks:
        return
    emb = get_embeddings()
    texts = [c.text for c in chunks]
    vectors = emb.embed(texts)
    ids = [f"{document_id}:{c.index}" for c in chunks]
    metadatas = [
        {
            "document_id": document_id,
            "filename": filename,
            "category": category,
            "page": c.page,
            "label": c.label or "",
            "chunk_index": c.index,
        }
        for c in chunks
    ]
    _collection().add(ids=ids, documents=texts, embeddings=vectors, metadatas=metadatas)


def delete_document(document_id: str) -> None:
    _collection().delete(where={"document_id": document_id})


def query(
    *,
    text: str,
    top_k: int,
    category: str | None = None,
    document_ids: list[str] | None = None,
) -> list[dict]:
    """Retrieval entry point (chat RAG, agent tool, /api/search).

    Pipeline: vector ANN → optional BM25 fusion (RRF) → optional cross-encoder
    rerank → top_k. Advanced stages are opt-in via env (SEARCH_HYBRID /
    SEARCH_RERANK) so the plain demo stays lightweight.
    """
    where = _build_where(category, document_ids)
    emb = get_embeddings()

    use_hybrid = settings.search_hybrid
    use_rerank = settings.search_rerank
    n_candidates = max(top_k, settings.retrieval_candidates) if (use_hybrid or use_rerank) else top_k

    qvec = emb.embed_query(text)
    res = _collection().query(
        query_embeddings=[qvec],
        n_results=n_candidates,
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    hits: list[dict] = []
    for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists):
        hits.append(
            {
                "id": chunk_id,
                "text": doc,
                "document_id": meta.get("document_id"),
                "filename": meta.get("filename"),
                "category": meta.get("category"),
                "page": meta.get("page"),
                "label": meta.get("label") or None,
                "chunk_index": meta.get("chunk_index"),
                # cosine distance -> similarity
                "score": round(1.0 - float(dist), 4),
            }
        )

    if use_hybrid:
        hits = _fuse_with_bm25(
            text=text, vector_hits=hits, n_candidates=n_candidates,
            category=category, document_ids=document_ids,
        )

    if use_rerank:
        from app.core.rerank import rerank

        hits = rerank(text, hits)[:top_k]
        import math

        for h in hits:
            # cross-encoder logits -> bounded 0..1 for the UI percent display
            h["score"] = round(1.0 / (1.0 + math.exp(-h["score"] * 4)), 4)
    else:
        hits = hits[:top_k]
    return hits


def _fuse_with_bm25(
    *,
    text: str,
    vector_hits: list[dict],
    n_candidates: int,
    category: str | None,
    document_ids: list[str] | None,
) -> list[dict]:
    from app.core.bm25 import bm25_search, rrf_fuse

    vec_ranking = {h["id"]: h["score"] for h in vector_hits}
    lex_ranking = bm25_search(
        text=text, top_k=n_candidates, category=category, document_ids=document_ids
    )
    fused = rrf_fuse([vec_ranking, lex_ranking])
    by_id = {h["id"]: h for h in vector_hits}
    ordered = [by_id[i] for i in sorted(fused, key=fused.get, reverse=True) if i in by_id]
    # BM25-only matches outside the vector pool are dropped: with the current
    # snapshot flow they would need a second Chroma lookup for marginal gain.
    return ordered[:n_candidates]


def _build_where(category: str | None, document_ids: list[str] | None) -> dict:
    clauses: list[dict] = []
    if category and category != "All":
        clauses.append({"category": category})
    if document_ids:
        clauses.append({"document_id": {"$in": document_ids}})
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) > 1:
        return {"$and": clauses}
    return {}
