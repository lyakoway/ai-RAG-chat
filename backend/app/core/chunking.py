"""Token-aware chunking that preserves page provenance.

Each page segment is split into overlapping token windows. Every resulting
chunk carries the page number/label so citations survive into retrieval.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings
from app.parsers.base import PageSegment

settings = get_settings()


@dataclass
class Chunk:
    text: str
    page: int
    label: str | None
    index: int  # global chunk index within the document


@lru_cache
def _encoder():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _split_tokens(text: str, size: int, overlap: int) -> list[str]:
    enc = _encoder()
    tokens = enc.encode(text)
    if len(tokens) <= size:
        return [text]
    out: list[str] = []
    step = max(size - overlap, 1)
    for start in range(0, len(tokens), step):
        window = tokens[start : start + size]
        if not window:
            break
        out.append(enc.decode(window))
        if start + size >= len(tokens):
            break
    return out


def chunk_segments(segments: list[PageSegment]) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for seg in segments:
        for piece in _split_tokens(seg.text, settings.chunk_size, settings.chunk_overlap):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(Chunk(text=piece, page=seg.page, label=seg.label, index=idx))
            idx += 1
    return chunks
