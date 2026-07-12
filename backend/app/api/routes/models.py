"""Available model list for the UI selector."""
from __future__ import annotations

from fastapi import APIRouter

from app.llm.registry import list_models
from app.schemas.dto import ModelInfo

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
def get_models():
    return list_models()
