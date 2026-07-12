"""Document endpoints: upload, list, categories, delete, download."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import vectorstore
from app.core.ingestion import ingest_document
from app.db.models import Document
from app.db.session import SessionLocal, get_db
from app.schemas.dto import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

ALLOWED_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}


def _run_ingestion(document_id: str, path: str) -> None:
    """Background task: uses its own DB session (request session is closed)."""
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc:
            ingest_document(db, doc, Path(path))
    finally:
        db.close()


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form("General"),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Формат {ext or '?'} не поддерживается. Разрешены: PDF, Word, Excel.")

    doc = Document(
        filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        category=(category or "General").strip() or "General",
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    dest = settings.upload_dir / f"{doc.id}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    doc.size_bytes = dest.stat().st_size
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background.add_task(_run_ingestion, doc.id, str(dest))
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(category: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.created_at.desc())
    if category and category != "All":
        stmt = stmt.where(Document.category == category)
    return list(db.scalars(stmt))


@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)):
    rows = db.execute(select(Document.category).distinct()).scalars()
    return sorted({c for c in rows if c})


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    return doc


@router.get("/{document_id}/file")
def download_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    ext = Path(doc.filename).suffix.lower()
    path = settings.upload_dir / f"{doc.id}{ext}"
    if not path.exists():
        raise HTTPException(404, "Файл отсутствует на диске")
    return FileResponse(path, filename=doc.filename, media_type=doc.content_type)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    vectorstore.delete_document(document_id)
    ext = Path(doc.filename).suffix.lower()
    path = settings.upload_dir / f"{doc.id}{ext}"
    path.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
