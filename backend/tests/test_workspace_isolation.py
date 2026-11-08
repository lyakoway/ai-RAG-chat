"""Stage 4B Step 3: cross-workspace API isolation matrix.

Demo-mode (conftest): X-Workspace header — временный workspace labeling до
auth (см. deps.get_workspace docstring). Ожидания:
- чужой ресурс → 404 (не 403/401 — не раскрывать существование);
- отсутствие header → default;
- SQL-слой (documents/conversations/messages/agent list) изолирован;
- Chroma retrieval НЕ изолирован (Step 4) — здесь не тестируется.
"""
from __future__ import annotations

import io
import json

WS_A = "ws-a"
WS_B = "ws-b"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_bytes(text: str) -> bytes:
    import io as _io

    from docx import Document

    buf = _io.BytesIO()
    d = Document()
    d.add_paragraph(text)
    d.save(buf)
    return buf.getvalue()


def _upload(client, ws: str, filename: str, text: str = "уникальное содержимое",
            category: str = "General") -> dict:
    r = client.post(
        "/api/documents",
        files={"file": (filename, _docx_bytes(text), DOCX_MIME)},
        data={"category": category},
        headers={"X-Workspace": ws},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _chat(client, ws: str | None, message: str = "вопрос по документам", conv_id: str | None = None) -> dict:
    headers = {"X-Workspace": ws} if ws else {}
    payload = {"message": message, "model": "mock"}
    if conv_id:
        payload["conversation_id"] = conv_id
    with client.stream("POST", "/api/chat", json=payload, headers=headers) as resp:
        assert resp.status_code == 200
        events: dict[str, dict] = {}
        event = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                events.setdefault(event, {})
            elif line.startswith("data:") and event:
                events[event] = json.loads(line[5:].strip())
        assert "done" in events, events
    return events



class TestDocumentsIsolation:
    def test_upload_scoped_and_invisible_cross_ws(self, client):
        doc = _upload(client, WS_A, "a-doc.docx")
        # ws_a видит
        assert client.get(
            f"/api/documents/{doc['id']}", headers={"X-Workspace": WS_A}
        ).status_code == 200
        # ws_b не видит: list и get
        listed = client.get("/api/documents", headers={"X-Workspace": WS_B}).json()
        assert doc["id"] not in {d["id"] for d in listed}
        r = client.get(f"/api/documents/{doc['id']}", headers={"X-Workspace": WS_B})
        assert r.status_code == 404

    def test_download_cross_ws_404(self, client):
        doc = _upload(client, WS_A, "dl.docx")
        r = client.get(
            f"/api/documents/{doc['id']}/file", headers={"X-Workspace": WS_B}
        )
        assert r.status_code == 404

    def test_delete_cross_ws_404_and_doc_alive(self, client):
        doc = _upload(client, WS_A, "del.docx")
        r = client.delete(f"/api/documents/{doc['id']}", headers={"X-Workspace": WS_B})
        assert r.status_code == 404
        assert client.get(
            f"/api/documents/{doc['id']}", headers={"X-Workspace": WS_A}
        ).status_code == 200

    def test_cross_ws_same_filename_isolated(self, client):
        """Изоляция не мешает: одинаковые имена в разных ws — независимые
        записи, каждая видна только своему workspace (workspace_id в API
        не раскрывается)."""
        d_a = _upload(client, WS_A, "same.docx", "текст A")
        d_b = _upload(client, WS_B, "same.docx", "текст B")
        assert d_a["id"] != d_b["id"]
        assert client.get(
            f"/api/documents/{d_a['id']}", headers={"X-Workspace": WS_A}
        ).status_code == 200
        assert client.get(
            f"/api/documents/{d_a['id']}", headers={"X-Workspace": WS_B}
        ).status_code == 404
        assert client.get(
            f"/api/documents/{d_b['id']}", headers={"X-Workspace": WS_B}
        ).status_code == 200
        assert client.get(
            f"/api/documents/{d_b['id']}", headers={"X-Workspace": WS_A}
        ).status_code == 404

    def test_categories_scoped(self, client):
        """Категории документа WS_A не видны в WS_B (общая test store БД —
        поэтому категория уникальна, а не 'General')."""
        unique_cat = "WsAUniqueCategory"
        _upload(client, WS_A, "cat-a.docx", category=unique_cat)
        cats_b = client.get("/api/documents/categories", headers={"X-Workspace": WS_B}).json()
        assert unique_cat not in cats_b
        cats_a = client.get("/api/documents/categories", headers={"X-Workspace": WS_A}).json()
        assert unique_cat in cats_a


class TestConversationsIsolation:
    def _create_conversation(self, client, ws: str) -> str:
        events = _chat(client, ws)
        return events["done"]["conversation_id"]

    def test_chat_creates_conversation_in_own_ws(self, client):
        """Conversation создан и виден только своему workspace (поле
        workspace_id в API-ответе не раскрывается)."""
        conv_id = self._create_conversation(client, WS_A)
        assert client.get(
            f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_A}
        ).status_code == 200
        assert client.get(
            f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_B}
        ).status_code == 404

    def test_conversation_invisible_cross_ws_list_and_get(self, client):
        conv_id = self._create_conversation(client, WS_A)
        listed = client.get("/api/conversations", headers={"X-Workspace": WS_B}).json()
        assert conv_id not in {c["id"] for c in listed}
        r = client.get(f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_B})
        assert r.status_code == 404
        body = r.json()["detail"]
        assert "не найден" in body  # 404-семантика, не раскрывающая ws

    def test_history_cross_ws_404(self, client):
        conv_id = self._create_conversation(client, WS_A)
        r = client.get(f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_B})
        assert r.status_code == 404
        assert not r.json().get("messages")

    def test_feedback_cross_ws_404(self, client):
        conv_id = self._create_conversation(client, WS_A)
        detail = client.get(
            f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_A}
        ).json()
        message_id = next(m["id"] for m in detail["messages"] if m["role"] == "assistant")
        r = client.post(
            f"/api/messages/{message_id}/feedback",
            json={"value": "up"},
            headers={"X-Workspace": WS_B},
        )
        assert r.status_code == 404
        # в своём ws — работает
        r = client.post(
            f"/api/messages/{message_id}/feedback",
            json={"value": "up"},
            headers={"X-Workspace": WS_A},
        )
        assert r.status_code == 200 and r.json()["feedback"] == "up"

    def test_rename_delete_cross_ws_404_and_preserved(self, client):
        conv_id = self._create_conversation(client, WS_A)
        r = client.patch(
            f"/api/conversations/{conv_id}",
            json={"title": "взломано"},
            headers={"X-Workspace": WS_B},
        )
        assert r.status_code == 404
        r = client.delete(f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_B})
        assert r.status_code == 404
        conv = client.get(f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_A})
        assert conv.status_code == 200
        assert conv.json()["title"] != "взломано"

    def test_chat_into_foreign_conversation_404(self, client):
        conv_id = self._create_conversation(client, WS_A)
        r = client.post(
            "/api/chat",
            json={"message": "привет", "model": "mock", "conversation_id": conv_id},
            headers={"X-Workspace": WS_B},
        )
        assert r.status_code == 404
        # conversation ws_a не получил новое сообщение
        detail = client.get(
            f"/api/conversations/{conv_id}", headers={"X-Workspace": WS_A}
        ).json()
        assert all(m["content"] != "привет" for m in detail["messages"])


class TestAgentScope:
    def test_agent_list_documents_scoped(self, tmp_path, client):
        """SQL-инструмент агента list_documents изолирован (retrieval — Step 4)."""
        from sqlalchemy import select

        from app.core.agent_tools import run_tool
        from app.db.models import Document
        from app.db.session import SessionLocal

        doc = _upload(client, WS_A, "agent-a.docx")
        s = SessionLocal()
        try:
            observation, _ = run_tool(
                "list_documents", {}, db=s, workspace_id=WS_B,
                category=None, document_ids=None, top_k=None,
            )
            payload = json.loads(observation)
            assert doc["id"] not in {d["id"] for d in payload}
            observation, _ = run_tool(
                "list_documents", {}, db=s, workspace_id=WS_A,
                category=None, document_ids=None, top_k=None,
            )
            payload = json.loads(observation)
            assert doc["id"] in {d["id"] for d in payload}
            assert s.execute(
                select(Document).where(Document.id == doc["id"])
            ).scalar().workspace_id == WS_A
        finally:
            s.close()


class TestDefaultWorkspace:
    def test_no_header_uses_default_and_isolated_from_named_ws(self, client):
        doc = _upload(client, "default", "no-header.docx")
        # default виден без header
        assert client.get(f"/api/documents/{doc['id']}").status_code == 200
        # и невидим из именованного ws
        r = client.get(f"/api/documents/{doc['id']}", headers={"X-Workspace": WS_A})
        assert r.status_code == 404

    def test_404_not_403_not_401(self, client):
        doc = _upload(client, WS_A, "sem.docx")
        r = client.get(f"/api/documents/{doc['id']}", headers={"X-Workspace": WS_B})
        assert r.status_code == 404
        assert r.status_code not in (401, 403)
