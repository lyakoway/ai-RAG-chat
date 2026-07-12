"""Conversation history endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation
from app.db.session import get_db
from app.schemas.dto import ConversationDetail, ConversationOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class RenameRequest(BaseModel):
    title: str


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
    return list(db.scalars(stmt))


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Диалог не найден")
    return conv


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(conversation_id: str, req: RenameRequest, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Диалог не найден")
    conv.title = req.title.strip() or conv.title
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Диалог не найден")
    db.delete(conv)
    db.commit()
