"""Document endpoints: upload, list, categories, demo pack, delete, download."""
from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import vectorstore
from app.core.ingestion import detect_lang_from_filename, ingest_document
from app.db.models import Document
from app.db.session import SessionLocal, get_db
from app.schemas.dto import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

ALLOWED_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}
DEMO_CATEGORY = "Demo"

# RU/EN-двойники демо-пака: удаление одного документа сносит и его перевод
# (принцип взаимности), поэтому пара должна быть известна заранее.
DEMO_PAIRS = {
    "Политика_удалённой_работы.docx": "remote_work_policy",
    "Remote_Work_Policy.docx": "remote_work_policy",
    "Руководство_пользователя.pdf": "user_guide",
    "User_Guide.pdf": "user_guide",
    "Тарифы_и_скидки.xlsx": "pricing",
    "Pricing_and_Discounts.xlsx": "pricing",
}


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
        # Предварительный язык виден сразу, до индексации (потом уточняется
        # по содержимому в ingest_document).
        lang=detect_lang_from_filename(file.filename or ""),
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


@router.post("/demo", response_model=list[DocumentOut], status_code=201)
def load_demo_documents(
    background: BackgroundTasks, db: Session = Depends(get_db)
) -> list[Document]:
    """One-click demo pack: copies backend/samples into the upload flow.

    Idempotent — files already present in the library (by filename) are skipped,
    so pressing the button twice never duplicates documents.
    """
    samples_dir = settings.samples_dir
    if not samples_dir.is_dir():
        raise HTTPException(404, "Демо-файлы недоступны на сервере")

    existing = set(db.scalars(select(Document.filename)))
    created: list[Document] = []
    for path in sorted(samples_dir.iterdir()):
        ext = path.suffix.lower()
        if ext not in ALLOWED_EXT or path.name in existing:
            continue
        doc = Document(
            filename=path.name,
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            category=DEMO_CATEGORY,
            status="processing",
            lang=detect_lang_from_filename(path.name),
            pair_key=DEMO_PAIRS.get(path.name),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        dest = settings.upload_dir / f"{doc.id}{ext}"
        shutil.copyfile(path, dest)
        doc.size_bytes = dest.stat().st_size
        db.add(doc)
        db.commit()
        db.refresh(doc)

        background.add_task(_run_ingestion, doc.id, str(dest))
        created.append(doc)
    return created


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
    # inline — иначе браузер не рендерит PDF в iframe просмотрщика
    # (при attachment окно открывается, а холст остаётся пустым).
    return FileResponse(
        path,
        filename=doc.filename,
        media_type=doc.content_type,
        content_disposition_type="inline",
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")

    # Принцип взаимности: у парных документов (RU/EN-двойники демо-пака)
    # удаляем сразу оба; обычные загрузки удаляются поодиночке.
    ids = [document_id]
    if doc.pair_key:
        ids += [
            d.id
            for d in db.scalars(
                select(Document).where(
                    Document.pair_key == doc.pair_key, Document.id != document_id
                )
            )
        ]

    for doc_id in ids:
        vectorstore.delete_document(doc_id)
        target = db.get(Document, doc_id)
        if target is None:
            continue
        ext = Path(target.filename).suffix.lower()
        (settings.upload_dir / f"{doc_id}{ext}").unlink(missing_ok=True)
        db.delete(target)
    db.commit()
