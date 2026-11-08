"""Conversation history endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, get_scoped, get_workspace
from app.db.models import Conversation, Message
from app.db.session import get_db
from app.schemas.dto import ConversationDetail, ConversationOut, MessageOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
feedback_router = APIRouter(prefix="/api/messages", tags=["conversations"])


class RenameRequest(BaseModel):
    title: str


class FeedbackRequest(BaseModel):
    # "up" | "down" | None — None снимает оценку.
    value: str | None = None


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db), ws: WorkspaceContext = Depends(get_workspace)
):
    stmt = (
        select(Conversation)
        .where(Conversation.workspace_id == ws.workspace_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(db.scalars(stmt))


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str, db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(get_workspace),
):
    conv = get_scoped(db, Conversation, conversation_id, ws.workspace_id)
    if not conv:
        raise HTTPException(404, "Диалог не найден")
    return conv


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: str, req: RenameRequest, db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(get_workspace),
):
    conv = get_scoped(db, Conversation, conversation_id, ws.workspace_id)
    if not conv:
        raise HTTPException(404, "Диалог не найден")
    conv.title = req.title.strip() or conv.title
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str, db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(get_workspace),
):
    conv = get_scoped(db, Conversation, conversation_id, ws.workspace_id)
    if not conv:
        raise HTTPException(404, "Диалог не найден")
    db.delete(conv)
    db.commit()


@feedback_router.post("/{message_id}/feedback", response_model=MessageOut)
def set_message_feedback(
    message_id: str, req: FeedbackRequest, db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(get_workspace),
):
    """Оценка ответа 👍/👎. Повторный клик (value=null) снимает оценку.

    Workspace изолирован: Message доступен только через родительскую
    Conversation (JOIN по workspace_id) — прямой db.get(Message) был
    cross-workspace утечкой (Stage 4B, миграционный план)."""
    if req.value not in ("up", "down", None):
        raise HTTPException(422, "value должен быть 'up', 'down' или null")
    msg = db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == message_id, Conversation.workspace_id == ws.workspace_id)
    ).scalar()
    if not msg or msg.role != "assistant":
        raise HTTPException(404, "Сообщение не найдено")
    msg.feedback = req.value
    db.commit()
    db.refresh(msg)
    return msg
