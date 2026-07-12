"""PDF parsing with per-page text extraction (page numbers preserved)."""
from __future__ import annotations

from pathlib import Path

from app.parsers.base import PageSegment, ParseError


def parse(path: Path) -> list[PageSegment]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"Не удалось прочитать PDF: {exc}") from exc

    segments: list[PageSegment] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(PageSegment(page=i, text=text))
    if not segments:
        raise ParseError("PDF не содержит извлекаемого текста (возможно, скан без OCR).")
    return segments
