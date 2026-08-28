"""Ingestion service: parse -> chunk -> embed -> index, updating the DB row."""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import vectorstore
from app.core.chunking import chunk_segments
from app.db.models import Document
from app.parsers.base import ParseError, page_count, parse_document

_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)
# CJK: хирагана/катакана (ja), хангыль (ko), унифицированные иероглифы (zh).
_KANA = re.compile(r"[\u3040-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_CJK_HAN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _lang_by_counts(text: str) -> str | None:
    """Побеждает алфавит с наибольшим числом символов (при равенстве — порядок ja, ko, zh, ru, en)."""
    counts = {
        "ja": len(_KANA.findall(text)),
        "ko": len(_HANGUL.findall(text)),
        "zh": len(_CJK_HAN.findall(text)),
        "ru": len(_CYRILLIC.findall(text)),
        "en": len(_LATIN.findall(text)),
    }
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None


def detect_lang(text: str) -> str | None:
    """Rough content language by letter counts; None if no known letters."""
    return _lang_by_counts(text[:3000])


def detect_lang_from_filename(name: str) -> str | None:
    """Provisional language for the upload record (before indexing).

    Needed so the documents panel can bucket files by UI language immediately,
    while they are still processing. Content-based detect_lang() refines it
    after parsing.
    """
    return _lang_by_counts(name)


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
        # Уточняем предварительный язык (из имени файла) по содержимому.
        detected = detect_lang("\n".join(s.text for s in segments))
        if detected:
            document.lang = detected
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
