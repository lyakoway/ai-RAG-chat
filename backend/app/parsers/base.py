"""Common parsing types + dispatch by content type / extension."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PageSegment:
    """A logical page/section of a document.

    `page` is a 1-based number used for citations. `label` is an optional
    human label (e.g. an Excel sheet name) shown alongside the page.
    """

    page: int
    text: str
    label: str | None = None


class ParseError(Exception):
    pass


def parse_document(path: Path, content_type: str) -> list[PageSegment]:
    from app.parsers import docx_parser, pdf_parser, xlsx_parser

    ext = path.suffix.lower()
    if ext == ".pdf" or content_type == "application/pdf":
        return pdf_parser.parse(path)
    if ext in {".docx", ".doc"} or "word" in content_type:
        return docx_parser.parse(path)
    if ext in {".xlsx", ".xls"} or "sheet" in content_type or "excel" in content_type:
        return xlsx_parser.parse(path)
    raise ParseError(f"Неподдерживаемый тип файла: {ext or content_type}")


def page_count(segments: list[PageSegment]) -> int:
    return max((s.page for s in segments), default=0)
