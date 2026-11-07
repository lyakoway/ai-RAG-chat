"""RAG pipeline: retrieve context, build a grounded prompt, dedupe sources."""
from __future__ import annotations

from app.config import get_settings
from app.core import vectorstore
from app.schemas.dto import Source

settings = get_settings()

SYSTEM_PROMPT_RU = """Ты — ассистент, отвечающий на вопросы СТРОГО по предоставленным \
документам. Правила:
- Используй только информацию из блока CONTEXT ниже.
- Если ответа в контексте нет — честно скажи, что не нашёл информации.
- Отвечай ПО-РУССКИ, кратко и по делу.
- Ссылайся на источники в формате [1], [2] по номерам фрагментов из контекста.

CONTEXT:
{context}
"""

SYSTEM_PROMPT_EN = """You are an assistant answering questions STRICTLY from the \
provided documents. Rules:
- Use only the information in the CONTEXT block below.
- If the answer isn't in the context, say honestly that you couldn't find it.
- Answer IN ENGLISH, concise and to the point.
- Cite sources as [1], [2] by the fragment numbers from the context.

CONTEXT:
{context}
"""

SYSTEM_PROMPTS = {"ru": SYSTEM_PROMPT_RU, "en": SYSTEM_PROMPT_EN}


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


def build_context(hits: list[dict], max_tokens: int | None = None) -> str:
    """Собирает блок CONTEXT. При заданном бюджете токенов чанки сверх бюджета
    отбрасываются целиком (не режутся посреди текста), минимум один чанк всегда
    попадает в контекст — чтобы grounded-ответ был возможен."""
    blocks = []
    for i, h in enumerate(hits, start=1):
        loc = f"стр. {h['page']}" if h.get("page") else ""
        if h.get("label"):
            loc = f"{loc} · {h['label']}" if loc else h["label"]
        header = f"[{i}] {h['filename']} ({loc})".strip()
        blocks.append(f"{header}\n{h['text']}")
    if max_tokens is not None and len(blocks) > 1:
        from app.core.chunking import _encoder

        enc = _encoder()
        kept: list[str] = []
        used = 0
        for block in blocks:
            block_tokens = len(enc.encode(block))
            if kept and used + block_tokens > max_tokens:
                break  # целые чанки сверх бюджета отбрасываются
            kept.append(block)
            used += block_tokens
        blocks = kept
    return "\n\n---\n\n".join(blocks)


def build_system_prompt(hits: list[dict], lang: str = "ru",
                        max_tokens: int | None = None) -> str:
    empty = "(нет релевантных фрагментов)" if lang == "ru" else "(no relevant fragments)"
    context = build_context(hits, max_tokens=max_tokens) if hits else empty
    template = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPT_RU)
    return template.format(context=context)


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
