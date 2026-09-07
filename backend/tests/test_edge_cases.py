"""Edge cases: пустой/битый/большой документ, деградация хранилища, honest-ответ."""
import io

import pytest
from docx import Document as DocxBuilder

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _find_doc(client, name):
    for d in client.get("/api/documents").json():
        if d["filename"] == name:
            return d
    return None


def _wait_status(client, name, statuses, tries=20):
    for _ in range(tries):
        d = _find_doc(client, name)
        if d and d["status"] in statuses:
            return d
        import time

        time.sleep(0.2)
    return d


class TestBrokenDocuments:
    def test_corrupted_pdf_rejected_with_error_status(self, client):
        r = client.post(
            "/api/documents",
            files={"file": ("broken.pdf", io.BytesIO(b"%PDF-1.4 garbage not a pdf"),
                            "application/pdf")},
            data={"category": "Edge"},
        )
        assert r.status_code == 201  # приём успешен, падает индексация
        d = _wait_status(client, "broken.pdf", {"ready", "error"})
        assert d["status"] == "error"
        assert d["error"]

    def test_corrupted_docx_rejected_with_error_status(self, client):
        r = client.post(
            "/api/documents",
            files={"file": ("broken.docx", io.BytesIO(b"this is not a zip"), DOCX_MIME)},
            data={"category": "Edge"},
        )
        assert r.status_code == 201
        d = _wait_status(client, "broken.docx", {"ready", "error"})
        assert d["status"] == "error"

    def test_corrupted_xlsx_rejected_with_error_status(self, client):
        r = client.post(
            "/api/documents",
            files={"file": ("broken.xlsx", io.BytesIO(b"not a spreadsheet"),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"category": "Edge"},
        )
        assert r.status_code == 201
        d = _wait_status(client, "broken.xlsx", {"ready", "error"})
        assert d["status"] == "error"
        assert "Ошибка обработки" in (d["error"] or "") or d["error"]

    def test_app_stays_functional_after_broken_uploads(self, client):
        """После битых загрузок поиск и чат продолжают работать."""
        assert client.get("/api/health").json()["status"] == "ok"
        r = client.get("/api/search", params={"q": "тариф", "top_k": 3})
        assert r.status_code == 200
        assert r.json()["results"]


class TestEmptyAndLargeDocuments:
    def test_empty_docx_marked_error(self, client):
        doc = DocxBuilder()  # ни одного абзаца
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        client.post(
            "/api/documents",
            files={"file": ("empty.docx", buf, DOCX_MIME)},
            data={"category": "Edge"},
        )
        d = _wait_status(client, "empty.docx", {"ready", "error"})
        assert d["status"] == "error"  # пустой документ не индексируется молча

    def test_large_document_splits_into_chunks(self, client):
        doc = DocxBuilder()
        doc.add_heading("Большой тестовый документ")
        for i in range(30):
            doc.add_paragraph(
                f"Раздел {i}: dettagli проекта, требования, ограничения и "
                "сопутствующие условия. " * 4
            )
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        r = client.post(
            "/api/documents",
            files={"file": ("large-edge.docx", buf, DOCX_MIME)},
            data={"category": "Edge"},
        )
        assert r.status_code == 201
        d = _wait_status(client, "large-edge.docx", {"ready", "error"})
        assert d["status"] == "ready"
        assert d["chunk_count"] >= 2  # большой документ нарезан на чанки

        # Поиск по большому документу работает и фильтруется по нему
        r = client.get(
            "/api/search",
            params={"q": "Раздел 7 dettagli", "top_k": 5,
                    "document_ids": d["id"]},
        )
        assert r.status_code == 200
        for res in r.json()["results"]:
            assert res["document_id"] == d["id"]


class TestHonestNoContextAnswer:
    def test_chat_with_unknown_document_ids_answers_without_fabrication(self, client, demo_loaded):
        """Нет релевантного контекста → честный ответ, а не выдумка."""
        r = client.post(
            "/api/chat",
            json={"message": "Какая столица Франции?", "model": "mock",
                  "mode": "rag", "lang": "ru", "document_ids": ["nonexistent"]},
        )
        assert r.status_code == 200
        events = _events(r.text)
        kinds = [e for e, _ in events]
        assert "done" in kinds
        sources = next(d["sources"] for e, d in events if e == "sources")
        assert sources == []  # контекста нет — источников нет
        answer = "".join(d.get("delta", "") for e, d in events if e == "token")
        assert "Париж" not in answer  # ничего не выдумано


def _events(text: str):
    import json

    out = []
    for frame in text.split("\n\n"):
        event, data = None, None
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if event and data:
            out.append((event, json.loads(data)))
    return out
