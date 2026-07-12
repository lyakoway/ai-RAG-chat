"""RAG pipeline: retrieve context, build a grounded prompt, dedupe sources."""
from __future__ import annotations

from app.config import get_settings
from app.core import vectorstore
from app.schemas.dto import Source

settings = get_settings()

SYSTEM_PROMPT = """Ты — ассистент, отвечающий на вопросы СТРОГО по предоставленным \
документам. Правила:
- Используй только информацию из блока CONTEXT ниже.
- Если ответа в контексте нет — честно скажи, что не нашёл информации.
- Отвечай на языке вопроса, кратко и по делу.
- Ссылайся на источники в формате [1], [2] по номерам фрагментов из контекста.

CONTEXT:
{context}
"""


def retrieve(
    *,
    query: str,
    top_k: int | None = None,
    category: str | None = None,
    document_ids: list[str] | None = None,
) -> list[dict]:
    k = top_k or settings.retrieval_top_k
    return vectorstore.query(
        text=query, top_k=k, category=category, document_ids=document_ids
    )


def build_context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        loc = f"стр. {h['page']}" if h.get("page") else ""
        if h.get("label"):
            loc = f"{loc} · {h['label']}" if loc else h["label"]
        header = f"[{i}] {h['filename']} ({loc})".strip()
        blocks.append(f"{header}\n{h['text']}")
    return "\n\n---\n\n".join(blocks)


def build_system_prompt(hits: list[dict]) -> str:
    context = build_context(hits) if hits else "(нет релевантных фрагментов)"
    return SYSTEM_PROMPT.format(context=context)


def to_sources(hits: list[dict]) -> list[Source]:
    sources: list[Source] = []
    for h in hits:
        snippet = h["text"].strip().replace("\n", " ")
        if len(snippet) > 320:
            snippet = snippet[:320].rstrip() + "…"
        sources.append(
            Source(
                document_id=h["document_id"],
                filename=h["filename"],
                page=h.get("page"),
                snippet=snippet,
                score=h.get("score"),
                chunk_index=h.get("chunk_index"),
            )
        )
    return sources
