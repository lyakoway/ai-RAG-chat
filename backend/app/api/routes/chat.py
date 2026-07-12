"""Streaming chat endpoint (Server-Sent Events).

Event protocol (each `data:` payload is JSON):
  event: sources   -> {"sources": [...], "conversation_id": "..."}
  event: token     -> {"delta": "text"}
  event: done      -> {"message_id": "...", "conversation_id": "..."}
  event: error     -> {"message": "..."}
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

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
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    # 1. Resolve / create the conversation and persist the user message.
    conv = db.get(Conversation, req.conversation_id) if req.conversation_id else None
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

    # 3. Retrieve grounding context.
    hits = rag.retrieve(
        query=req.message,
        top_k=req.top_k,
        category=req.category,
        document_ids=req.document_ids,
    )
    sources = rag.to_sources(hits)
    system = rag.build_system_prompt(hits)
    provider = get_provider(req.model)
    conv_id = conv.id

    async def gen() -> AsyncIterator[str]:
        yield _sse("sources", {
            "conversation_id": conv_id,
            "sources": [s.model_dump() for s in sources],
        })
        buffer: list[str] = []
        try:
            async for delta in provider.stream(system, history):
                buffer.append(delta)
                yield _sse("token", {"delta": delta})
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"Ошибка модели: {exc}"})

        # 4. Persist the assistant message + citations (fresh session).
        answer = "".join(buffer)
        db2 = SessionLocal()
        try:
            msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content=answer,
                sources=[s.model_dump() for s in sources],
            )
            db2.add(msg)
            db2.commit()
            db2.refresh(msg)
            message_id = msg.id
        finally:
            db2.close()

        yield _sse("done", {"message_id": message_id, "conversation_id": conv_id})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _title_from(message: str) -> str:
    text = message.strip().replace("\n", " ")
    return (text[:48] + "…") if len(text) > 48 else (text or "Новый чат")
