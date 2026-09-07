"""Citations и source mapping: страница-источник, сниппеты, обрезка, фильтры."""
import io

import pytest
from docx import Document as DocxBuilder

from app.core import rag

RU_PDF = "Руководство_пользователя.pdf"


def _upload_docx(client, name, builder, category="Edge"):
    buf = io.BytesIO()
    builder.save(buf)
    buf.seek(0)
    r = client.post(
        "/api/documents",
        files={"file": (name, buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"category": category},
    )
    assert r.status_code == 201
    return r.json()


class TestSourceMapping:
    def test_to_sources_maps_fields(self, demo_loaded):
        hits = rag.retrieve(query="сколько стоит тариф старт", top_k=2)
        sources = rag.to_sources(hits)
        assert len(sources) == len(hits)
        for s in sources:
            assert s.document_id and s.filename
            assert s.snippet and s.score is not None

    def test_pdf_chunks_carry_page_numbers(self, demo_loaded):
        hits = rag.retrieve(query="двухфакторная аутентификация", top_k=5)
        pdf_hits = [h for h in hits if h["filename"] == RU_PDF]
        assert pdf_hits
        assert all(1 <= h["page"] <= 3 for h in pdf_hits)

    def test_build_context_includes_page(self, demo_loaded):
        hits = rag.retrieve(query="двухфакторная аутентификация", top_k=3)
        pdf_hits = [h for h in hits if h["filename"] == RU_PDF]
        if pdf_hits:
            context = rag.build_context(pdf_hits[:1])
            assert f"стр. {pdf_hits[0]['page']}" in context

    def test_snippet_truncated_over_320_chars(self):
        long_text = "А" * 500
        hit = {"document_id": "d1", "filename": "f.pdf", "page": 2,
               "text": long_text, "score": 0.9, "chunk_index": 0}
        s = rag.to_sources([hit])[0]
        assert len(s.snippet) <= 321
        assert s.snippet.endswith("…")

    def test_snippet_strips_newlines(self):
        hit = {"document_id": "d1", "filename": "f.pdf", "page": 1,
               "text": "строка1\nстрока2\nстрока3", "score": 0.8, "chunk_index": 0}
        s = rag.to_sources([hit])[0]
        assert "\n" not in s.snippet


class TestCitationFlow:
    def test_chat_sources_carry_filenames_and_pages(self, client, demo_loaded):
        r = client.post(
            "/api/chat",
            json={"message": "Сколько дней отпуск?", "model": "mock",
                  "mode": "rag", "lang": "ru"},
        )
        events = _sse_events_of(r.text)
        sources = next(d["sources"] for e, d in events if e == "sources")
        assert sources
        assert all(s["filename"] for s in sources)
        assert any(s.get("page") for s in sources)

    def test_document_filter_limits_citation_sources(self, client, demo_loaded):
        docs = client.get("/api/documents").json()
        target = next(d for d in docs if d["filename"] == RU_PDF)
        r = client.post(
            "/api/chat",
            json={"message": "пароль и аутентификация", "model": "mock",
                  "mode": "rag", "lang": "ru", "document_ids": [target["id"]]},
        )
        events = _sse_events_of(r.text)
        sources = next(d["sources"] for e, d in events if e == "sources")
        assert all(s["document_id"] == target["id"] for s in sources)


def _sse_events_of(text: str):
    import json

    events = []
    for frame in text.split("\n\n"):
        event, data = None, None
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if event and data:
            events.append((event, json.loads(data)))
    return events
