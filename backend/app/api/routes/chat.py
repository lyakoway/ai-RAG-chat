"""Streaming chat endpoint (Server-Sent Events).

Event protocol (each `data:` payload is JSON):
  event: agent_step -> {"index", "type", "name", "args", "ok", "detail"}  (agent mode)
  event: sources    -> {"sources": [...], "conversation_id": "..."}
  event: token      -> {"delta": "text"}
  event: done       -> {"message_id": "...", "conversation_id": "..."}
  event: error      -> {"message": "..."}
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import agent as agent_loop
from app.core import rag
from app.db.models import Conversation, Message
from app.db.session import SessionLocal, get_db
from app.llm.base import ChatMessage
from app.llm.registry import get_provider
from app.schemas.dto import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])

_HISTORY_LIMIT = 8  # last N messages fed back to the model for context


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(
    req: ChatRequest, background: BackgroundTasks, db: Session = Depends(get_db)
):
    mode = (req.mode or "rag").lower()
    if mode not in ("rag", "agent"):
        mode = "rag"

    # 1. Resolve / create the conversation and persist the user message.
    conv = db.get(Conversation, req.conversation_id) if req.conversation_id else None
    conv_created = conv is None
    if conv is None:
        conv = Conversation(title=_title_from(req.message), model=req.model)
        db.add(conv)
        db.commit()
        db.refresh(conv)

    db.add(Message(conversation_id=conv.id, role="user", content=req.message))
    conv.model = req.model
    db.commit()

    # 2. Build history for the model (chronological, capped).
    history_rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(_HISTORY_LIMIT)
    ).all()
    history = [ChatMessage(role=m.role, content=m.content) for m in reversed(history_rows)]

    provider = get_provider(req.model)
    conv_id = conv.id

    if mode == "agent":
        # Own DB session for the stream — request-scoped `db` closes when the
        # route returns, before the generator finishes.
        return StreamingResponse(
            _gen_agent(
                req=req,
                history=history,
                provider=provider,
                conv_id=conv_id,
                is_new=conv_created,
                background=background,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- Classic RAG (single retrieve → answer) ----
    hits = rag.retrieve(
        query=req.message,
        top_k=req.top_k,
        category=req.category,
        document_ids=req.document_ids,
    )
    sources = rag.to_sources(hits)
    system = rag.build_system_prompt(hits, req.lang)
    followups = _static_followups([s.filename for s in sources], req.lang)

    async def gen_rag() -> AsyncIterator[str]:
        yield _sse("sources", {
            "conversation_id": conv_id,
            "sources": [s.model_dump() for s in sources],
        })
        if followups:
            yield _sse("followups", {"followups": followups})
        buffer: list[str] = []
        try:
            async for delta in provider.stream(system, history, req.lang):
                buffer.append(delta)
                yield _sse("token", {"delta": delta})
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"Ошибка модели: {exc}"})

        answer = "".join(buffer)
        message_id = _persist_assistant(
            conv_id, answer, [s.model_dump() for s in sources], None
        )
        yield _sse("done", {"message_id": message_id, "conversation_id": conv_id})

        # Автозаголовок — фоновой задачей ПОСЛЕ закрытия стрима: держать SSE
        # открытым на время LLM-вызова нельзя (прокси придерживает хвост,
        # и done не доходит до клиента).
        if conv_created:
            background.add_task(
                _generate_title_task, provider, req.lang, req.message, answer, conv_id
            )

    return StreamingResponse(
        gen_rag(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _gen_agent(
    *,
    req: ChatRequest,
    history: list[ChatMessage],
    provider,
    conv_id: str,
    is_new: bool = False,
    background: BackgroundTasks,
) -> AsyncIterator[str]:
    buffer: list[str] = []
    sources_payload: list[dict] = []
    steps: list[dict] = []
    db_agent = SessionLocal()
    try:
        try:
            async for event, data in agent_loop.run_agent(
                provider=provider,
                history=history,
                lang=req.lang,
                db=db_agent,
                category=req.category,
                document_ids=req.document_ids,
                top_k=req.top_k,
                user_message=req.message,
            ):
                if event == "agent_step":
                    steps.append(data)
                    yield _sse("agent_step", {**data, "conversation_id": conv_id})
                elif event == "sources":
                    sources_payload = data.get("sources") or []
                    yield _sse(
                        "sources",
                        {"conversation_id": conv_id, "sources": sources_payload},
                    )
                elif event == "token":
                    delta = data.get("delta") or ""
                    buffer.append(delta)
                    yield _sse("token", {"delta": delta})
                elif event == "agent_meta":
                    steps = data.get("steps") or steps
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"Ошибка агента: {exc}"})
    finally:
        db_agent.close()

    answer = "".join(buffer)
    message_id = _persist_assistant(conv_id, answer, sources_payload, steps)
    yield _sse("done", {"message_id": message_id, "conversation_id": conv_id})

    # Автозаголовок нового диалога — фоновой задачей после закрытия стрима.
    if is_new:
        background.add_task(
            _generate_title_task, provider, req.lang, req.message, answer, conv_id
        )


def _persist_assistant(
    conv_id: str,
    answer: str,
    sources: list[dict] | None,
    agent_steps: list[dict] | None,
) -> str:
    db2 = SessionLocal()
    try:
        msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=answer,
            sources=sources,
            agent_steps=agent_steps,
        )
        db2.add(msg)
        db2.commit()
        db2.refresh(msg)
        return msg.id
    finally:
        db2.close()


def _title_from(message: str) -> str:
    text = message.strip().replace("\n", " ")
    return (text[:48] + "…") if len(text) > 48 else (text or "Новый чат")


_TITLE_SYSTEM_RU = (
    "Ты придумываешь заголовок для диалога с ассистентом. Верни ТОЛЬКО JSON без "
    'пояснений и без markdown: {"title": "заголовок в 3-6 словах"}. Заголовок — на русском.'
)
_TITLE_SYSTEM_EN = (
    'You invent a title for a chat with an assistant. Return ONLY JSON, no explanations '
    'or markdown: {"title": "title in 3-6 words"}. Title in English.'
)


def _static_followups(source_filenames: list[str], lang: str) -> list[str]:
    """Follow-up подсказки строятся из реальной выдачи поиска (без LLM-вызова,
    по образцу ai-data-pilot): спрашивают про ДРУГИЕ найденные документы,
    поэтому каждый раз подстраиваются под библиотеку и запрос.
    """
    from pathlib import PurePath

    def stem(name: str) -> str:
        s = PurePath(name).stem
        return s[:32] + "…" if len(s) > 32 else s

    # Уникальные документы выдачи; топовый — углубляем, про другие — спрашиваем.
    seen: set[str] = set()
    unique: list[str] = []
    for name in source_filenames:
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    top = unique[0] if unique else None
    others = unique[1:3]

    if lang == "en":
        out = [f"Tell me more about “{stem(n)}”" for n in ([top] if top else [])]
        out += [f"What does “{stem(n)}” say about this?" for n in others]
        filler = ["What numbers and deadlines are mentioned?", "Any exceptions or limitations?"]
    else:
        out = [f"Расскажи подробнее про «{stem(n)}»" for n in ([top] if top else [])]
        out += [f"Что говорится в «{stem(n)}»?" for n in others]
        filler = ["Какие цифры и сроки упоминаются?", "Есть ли исключения или ограничения?"]
    # Добираем универсальными, если других документов мало.
    for q in filler:
        if len(out) >= 3:
            break
        out.append(q)
    return out[:3]


async def _generate_title(
    provider, lang: str, question: str, answer: str
) -> str | None:
    """LLM-заголовок диалога по первому обмену; None при любой неудаче."""
    if getattr(provider, "provider", "") == "mock":
        return None
    system = _TITLE_SYSTEM_RU if lang == "ru" else _TITLE_SYSTEM_EN
    user = f"Вопрос: {question[:500]}\n\nОтвет ассистента: {answer[:1000]}"
    chunks: list[str] = []
    async for delta in provider.stream(system, [ChatMessage(role="user", content=user)], lang):
        chunks.append(delta)
    text = "".join(chunks)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    title = " ".join(title.split()).strip(" \"'«»").strip()
    if len(title) > 60:
        title = title[:57].rstrip() + "…"
    return title or None


async def _generate_title_task(
    provider, lang: str, question: str, answer: str, conv_id: str
) -> None:
    """Фоновая задача: LLM-заголовок + запись в БД (после закрытия стрима)."""
    title = await _generate_title(provider, lang, question, answer)
    if not title:
        return
    db = SessionLocal()
    try:
        conv = db.get(Conversation, conv_id)
        if conv:
            conv.title = title
            db.add(conv)
            db.commit()
    finally:
        db.close()
