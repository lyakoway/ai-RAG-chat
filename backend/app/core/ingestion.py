"""Ingestion service: parse -> chunk -> embed -> index, updating the DB row."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core import vectorstore
from app.core.chunking import chunk_segments
from app.db.models import Document
from app.parsers.base import ParseError, page_count, parse_document


def ingest_document(db: Session, document: Document, path: Path) -> None:
    """Runs synchronously (called from a background task). Updates status."""
    try:
        segments = parse_document(path, document.content_type)
        chunks = chunk_segments(segments)
        vectorstore.add_document_chunks(
            document_id=document.id,
            filename=document.filename,
            category=document.category,
            chunks=chunks,
        )
        document.page_count = page_count(segments)
        document.chunk_count = len(chunks)
        document.status = "ready"
        document.error = None
    except ParseError as exc:
        document.status = "error"
        document.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        document.status = "error"
        document.error = f"Ошибка обработки: {exc}"
    finally:
        db.add(document)
        db.commit()
