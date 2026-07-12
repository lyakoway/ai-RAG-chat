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
    """Return retrieved chunks with metadata + similarity score (0..1)."""
    where = _build_where(category, document_ids)
    emb = get_embeddings()
    qvec = emb.embed_query(text)
    res = _collection().query(
        query_embeddings=[qvec],
        n_results=top_k,
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    hits: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append(
            {
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
    return hits


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
