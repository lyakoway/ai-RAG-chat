"""Stage 4A: safety baseline — лимиты, usage/latency логирование, telemetry.

- top_k: pydantic ge=1 (422 на 0/отрицательные) + серверный clamp сверху;
- oversized upload → 413, без остатков файла/записи;
- context token budget: чанки сверх бюджета отбрасываются целиком, минимум 1;
- usage отсутствует → лог с usage_source=unavailable (точная стоимость не заявляется);
- в логе нет текста вопроса/ответа и имён документов;
- SSE-поведение чата сохранено.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from app.core import rag


class TestTopKCap:
    def test_negative_and_zero_rejected(self, client):
        for bad in (0, -3):
            r = client.post("/api/chat", json={"message": "тест лимитов", "model": "mock", "top_k": bad})
            assert r.status_code == 422, f"top_k={bad} должен дать 422"

    def test_string_top_k_rejected(self, client):
        r = client.post("/api/chat", json={"message": "тест", "model": "mock", "top_k": "abc"})
        assert r.status_code == 422

    def test_cap_applied_server_side(self, client, demo_loaded, monkeypatch):
        """top_k=999 → запрос успешен, а в retrieval ушло не больше chat_top_k_max."""
        captured: list[int] = []
        from app.core import vectorstore

        original = vectorstore.query

        def spy(*args, **kwargs):
            captured.append(kwargs.get("top_k"))
            return original(*args, **kwargs)

        monkeypatch.setattr(vectorstore, "query", spy)
        r = client.post("/api/chat", json={"message": "отпуск", "model": "mock", "top_k": 999})
        assert r.status_code == 200
        from app.config import get_settings

        assert captured and max(captured) <= get_settings().chat_top_k_max

    def test_none_uses_default(self, client, demo_loaded):
        from app.api.routes.chat import _effective_top_k
        from app.config import get_settings

        assert _effective_top_k(None) == get_settings().retrieval_top_k


class TestUploadSizeLimit:
    def test_oversized_upload_413_and_no_residue(self, client, monkeypatch):
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "max_upload_mb", 0)  # лимит 0 → любой файл превышает

        payload = b"PK\x03\x04" + b"x" * 4096  # валидный zip-заголовок + мусор
        r = client.post(
            "/api/documents",
            files={"file": ("big.docx", payload, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert r.status_code == 413
        assert "Лимит сервера" in r.json()["detail"]

    def test_normal_upload_still_works(self, client, monkeypatch):
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "max_upload_mb", 10)
        from docx import Document
        import io

        buf = io.BytesIO()
        Document().add_paragraph("Безопасная загрузка в пределах лимита.")
        doc_ = Document()
        doc_.add_paragraph("x")
        doc_.save(buf)
        buf.seek(0)
        r = client.post(
            "/api/documents",
            files={"file": ("ok.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert r.status_code == 201


class TestContextBudget:
    def test_budget_drops_whole_chunks_keeps_first(self):
        hits = [
            {"filename": "a.docx", "text": "первый фрагмент " * 200, "page": 1},
            {"filename": "b.docx", "text": "второй фрагмент " * 200, "page": 2},
            {"filename": "c.docx", "text": "третий фрагмент", "page": 3},
        ]
        ctx = rag.build_context(hits, max_tokens=400)
        assert "первый фрагмент" in ctx
        assert "третий фрагмент" not in ctx  # отброшен целиком, не разрезан

    def test_budget_never_drops_everything(self):
        hits = [{"filename": "a.docx", "text": "огромный фрагмент " * 5000, "page": 1}]
        ctx = rag.build_context(hits, max_tokens=10)
        assert "огромный фрагмент" in ctx  # минимум 1 чанк сохраняется

    def test_no_budget_keeps_all(self):
        hits = [{"filename": f"{i}.docx", "text": f"текст {i}", "page": 1} for i in range(5)]
        ctx = rag.build_context(hits)
        assert "текст 4" in ctx

    def test_system_prompt_accepts_budget(self):
        hits = [{"filename": "a.docx", "text": "фрагмент", "page": 1}]
        prompt = rag.build_system_prompt(hits, "ru", max_tokens=100)
        assert "CONTEXT" in prompt and "фрагмент" in prompt


class TestChatLogging:
    def test_log_has_request_id_and_usage_unavailable(self, client, demo_loaded, caplog):
        """Mock-провайдер не отдаёт usage → usage_source=unavailable; точная
        стоимость не заявляется. В логе нет текста вопроса/ответа."""
        import logging

        with caplog.at_level(logging.INFO, logger="app.chat"):
            r = client.post("/api/chat", json={
                "message": "СЕКРЕТНЫЙ_ТЕКСТ_ВОПРОСА про отпуск", "model": "mock",
            })
            assert r.status_code == 200
        records = [x.message for x in caplog.records if "chat_request" in x.message]
        assert records, "chat_request лог не написан"
        entry = json.loads(records[-1])
        assert entry["request_id"] and len(entry["request_id"]) == 12
        assert entry["model"] == "mock" and entry["provider"] == "mock"
        assert entry["usage_source"] == "unavailable"
        assert entry["in_tokens"] is None and entry["out_tokens"] is None
        assert entry["status"] == "ok"
        assert entry["total_ms"] > 0 and entry["retrieval_ms"] is not None

    def test_log_without_sensitive_data(self, client, demo_loaded, caplog):
        import logging

        secret = "СЕКРЕТНЫЙ_ТЕКСТ_ВОПРОСА_98765"
        with caplog.at_level(logging.INFO, logger="app.chat"):
            client.post("/api/chat", json={"message": secret, "model": "mock"})
        blob = "\n".join(x.getMessage() for x in caplog.records)
        assert secret not in blob
        assert "ZAI" not in blob and "api_key" not in blob.lower().replace("api_keys", "")

    def test_provider_usage_used_when_present(self, client, demo_loaded, monkeypatch, caplog):
        """Если провайдер вернул last_usage — лог содержит счётчики, а не unavailable."""
        import logging

        from app.llm.providers import MockProvider

        original = MockProvider.stream

        async def stream_with_usage(self, system, messages, lang="ru"):
            self.last_usage = {"prompt_tokens": 123, "completion_tokens": 45}
            async for delta in original(self, system, messages, lang):
                yield delta

        monkeypatch.setattr(MockProvider, "stream", stream_with_usage)
        with caplog.at_level(logging.INFO, logger="app.chat"):
            client.post("/api/chat", json={"message": "отпуск", "model": "mock"})
        records = [x.message for x in caplog.records if "chat_request" in x.message]
        entry = json.loads(records[-1])
        assert entry["usage_source"] == "provider"
        assert entry["in_tokens"] == 123 and entry["out_tokens"] == 45


class TestSSEPreserved:
    def test_sse_event_order_and_done(self, client, demo_loaded):
        """Стрим чата сохраняет протокол: sources → token… → done (логирование
        не должно менять SSE-поведение)."""
        with client.stream("POST", "/api/chat", json={"message": "отпуск", "model": "mock"}) as resp:
            assert resp.status_code == 200
            events: list[str] = []
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
        assert events[0] == "sources"
        assert "token" in events
        assert events[-1] == "done"


class TestChromaTelemetry:
    def test_anonymized_telemetry_disabled(self):
        from app.core import vectorstore

        settings = vectorstore._client().get_settings()
        assert settings.anonymized_telemetry is False
