"""Pydantic DTOs for the API layer."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- Documents ----------
class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    category: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: str
    error: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Sources / citations ----------
class Source(BaseModel):
    document_id: str
    filename: str
    page: int | None = None
    snippet: str
    score: float | None = None
    chunk_index: int | None = None


# ---------- Chat ----------
class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str = "mock"
    category: str | None = None                 # filter retrieval by category
    document_ids: list[str] | None = None        # or restrict to specific docs
    top_k: int | None = None
    lang: str = "ru"                             # UI language: "ru" | "en"


# ---------- Conversations ----------
class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sources: list[Source] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: str
    title: str
    model: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


# ---------- Models ----------
class ModelInfo(BaseModel):
    id: str            # e.g. "openai:gpt-4o-mini"
    provider: str      # openai | anthropic | ollama | mock
    label: str
    available: bool    # key present / reachable
    description: str = ""
