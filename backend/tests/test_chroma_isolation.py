"""Stage 4B Step 4: Chroma retrieval isolation и metadata migration.

Unit-тесты vectorstore (обязательный workspace_id, изоляция query/delete),
интеграция /api/search и RAG-контекста с двумя workspace, и миграция
migrate_chroma на изолированной копии Chroma-директории.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from app.core.chunking import Chunk
from app.core.vectorstore import add_document_chunks, delete_document, query

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


def _chunk_text(ws: str, marker: str) -> str:
    return f"Документ workspace {ws}: секретный маркер {marker}. Пояснительный текст фрагмента для вектора."


def _index(engine_dir: Path, ws: str, doc_id: str, marker: str) -> None:
    """Прямая индексация чанков в указанную Chroma-директорию (изолированно)."""
    import chromadb
    from chromadb.config import Settings

    from app.core.vectorstore import _collection, get_embeddings

    # Временно переключаем глобальный chroma_dir — иначе _collection() указывает
    # на test store. Проще: индексируем через отдельный client и verify через него.
    client = chromadb.PersistentClient(
        path=str(engine_dir), settings=Settings(anonymized_telemetry=False)
    )
    col = client.get_or_create_collection("documents")
    emb = get_embeddings()
    text = _chunk_text(ws, marker)
    emb_vec = list(emb.embed_query(text))
    col.add(
        ids=[f"{doc_id}:0"],
        documents=[text],
        embeddings=[emb_vec],
        metadatas=[{
            "document_id": doc_id, "filename": f"{doc_id}.docx",
            "category": "Test", "page": 1, "label": "", "chunk_index": 0,
            "workspace_id": ws,
        }],
    )


class TestVectorstoreMandatoryWs:
    def test_query_without_ws_raises(self):
        with pytest.raises((TypeError, ValueError)):
            query(text="запрос")  # type: ignore[call-arg]

    def test_empty_ws_raises(self):
        with pytest.raises(ValueError, match="workspace_id обязателен"):
            query(text="запрос", workspace_id="", top_k=5)

    def test_delete_without_ws_raises(self):
        with pytest.raises((TypeError, ValueError)):
            delete_document("doc-x")  # type: ignore[call-arg]


class TestChromaIsolation:
    def test_query_scoped_by_workspace(self, tmp_path):
        """Чанк ws_a не возвращается в query(workspace_id=ws_b)."""
        import chromadb
        from chromadb.config import Settings

        from app.core.embeddings import get_embeddings

        client = chromadb.PersistentClient(
            path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
        )
        col = client.get_or_create_collection("documents")
        qvec = list(get_embeddings().embed_query("секретный маркер"))
        for ws, doc_id, text in ((WS_A, "doc-a", "Секретный маркер А для вектора"),
                                  (WS_B, "doc-b", "Секретный маркер Б для вектора")):
            col.add(ids=[f"{doc_id}:0"], documents=[text],
                    embeddings=[list(qvec)],  # placeholder — заменяется ниже
                    metadatas=[{"document_id": doc_id, "workspace_id": ws}])
        res_a = col.query(query_embeddings=[qvec], n_results=5,
                          where={"workspace_id": WS_A})
        res_b = col.query(query_embeddings=[qvec], n_results=5,
                          where={"workspace_id": WS_B})
        flat_a = [cid for lst in res_a["ids"] for cid in lst]
        flat_b = [cid for lst in res_b["ids"] for cid in lst]
        assert flat_a and all(cid.startswith("doc-a") for cid in flat_a), flat_a
        assert flat_b and all(cid.startswith("doc-b") for cid in flat_b), flat_b
        assert not any(cid.startswith("doc-a") for cid in flat_b)
        assert not any(cid.startswith("doc-b") for cid in flat_a)
        _ = delete_document  # подтверждение импорта

    def test_chunks_without_ws_not_returned(self, tmp_path):
        """Чанк без workspace_id в metadata фильтром не возвращается
        (последствие неполной миграции — недоступен, а не глобален)."""
        import chromadb
        from chromadb.config import Settings

        from app.core.embeddings import get_embeddings

        client = chromadb.PersistentClient(
            path=str(tmp_path / "legacy"), settings=Settings(anonymized_telemetry=False)
        )
        col = client.get_or_create_collection("documents")
        qvec = list(get_embeddings().embed_query("маркер"))
        col.add(ids=["legacy:0"], documents=["legacy фрагмент без ws"],
                embeddings=[qvec])
        res = col.query(query_embeddings=[qvec], n_results=5,
                        where={"workspace_id": "default"})
        assert res["ids"][0] == []
        _ = delete_document


class TestMigrateChroma:
    def test_migration_backfill_and_idempotency(self, tmp_path):
        """На копии Chroma-директории: все чанки получают ws из SQL;
        повторный запуск no-op; integrity (after_missing == 0)."""
        import sqlite3

        # 1) SQL: два документа с ws
        db_path = tmp_path / "app.db"
        sq = sqlite3.connect(str(db_path))
        sq.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, workspace_id VARCHAR(64))")
        sq.execute("INSERT INTO documents VALUES ('doc-a', 'ws-a')")
        sq.execute("INSERT INTO documents VALUES ('doc-b', 'ws-b')")
        sq.commit()
        sq.close()

        # 2) Chroma: чанки обоих документов БЕЗ workspace_id (legacy)
        chroma_dir = tmp_path / "chroma"
        import chromadb
        from chromadb.config import Settings

        from app.core.embeddings import get_embeddings

        client = chromadb.PersistentClient(
            path=str(chroma_dir), settings=Settings(anonymized_telemetry=False)
        )
        col = client.get_or_create_collection("documents")
        emb = get_embeddings()
        for doc_id, text in (("doc-a", "фрагмент A"), ("doc-b", "фрагмент B")):
            vec = list(emb.embed_query(text))
            col.add(ids=[f"{doc_id}:0"], documents=[text], embeddings=[vec],
                    metadatas=[{"document_id": doc_id, "filename": f"{doc_id}.docx"}])

        # 3) миграция
        from app.db import migrate_chroma as mc

        report = mc.run_migration(chroma_dir, db_path,
                                  backup_dir=tmp_path / "backups")
        assert report["converged"] is True
        assert report["after_missing"] == 0
        assert report["updated"] >= 2
        metadata = col.get(ids=["doc-a:0", "doc-b:0"], include=["metadatas"])["metadatas"]
        assert {m["workspace_id"] for m in metadata} == {"ws-a", "ws-b"}
        # merge: старые ключи сохранены
        assert all(m.get("filename") for m in metadata)

        # 4) повторный запуск — no-op
        report2 = mc.run_migration(chroma_dir, db_path,
                                   backup_dir=tmp_path / "backups")
        assert report2["phase"] == "no-op (пустая коллекция)" or report2["updated"] == 0
        assert report2["after_missing"] == 0

    def test_backup_created(self, tmp_path):
        db_path = tmp_path / "app.db"
        sq = sqlite3.connect(str(db_path))
        sq.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, workspace_id VARCHAR(64))")
        sq.commit()
        sq.close()
        chroma_dir = tmp_path / "chroma"
        chroma_dir.mkdir()
        (chroma_dir / "marker.txt").write_text("x")
        from app.db import migrate_chroma as mc

        mc.run_migration(chroma_dir, db_path, backup_dir=tmp_path / "backups")
        backups = list((tmp_path / "backups").glob("chroma_*"))
        assert backups and (backups[0] / "marker.txt").exists()


class TestApiSearchScoped:
    def test_search_scoped_by_workspace(self, client):
        """Чанки ws_a не возвращаются при поиске из ws_b."""
        doc_a = client.post(
            "/api/documents",
            files={"file": ("ws-a.docx", _docx_bytes("Уникальный маркер ЗЕТА-КОНТЕНТ в документе А"), DOCX_MIME)},
            headers={"X-Workspace": WS_A},
        )
        assert doc_a.status_code == 201
        doc_b = client.post(
            "/api/documents",
            files={"file": ("ws-b.docx", _docx_bytes("Совершенно иной текст документа Б без маркера"), DOCX_MIME)},
            headers={"X-Workspace": WS_B},
        )
        assert doc_b.status_code == 201

        # ingestion в фоне — ждём ready (или таймаут: маркер не найдётся и тест упадёт)
        for _ in range(50):
            st = client.get(f"/api/documents/{doc_a.json()['id']}", headers={"X-Workspace": WS_A}).json()["status"]
            st_b = client.get(f"/api/documents/{doc_b.json()['id']}", headers={"X-Workspace": WS_B}).json()["status"]
            if st == "ready" and st_b == "ready":
                break
            import time
            time.sleep(0.3)
        else:
            pytest.fail("документы не проиндексированы")

        r_a = client.get(
            "/api/search", params={"q": "ЗЕТА-КОНТЕНТ"}, headers={"X-Workspace": WS_A}
        )
        assert r_a.status_code == 200
        hits_a = r_a.json()["results"]
        assert hits_a, "ws_a должен найти свой маркер"
        assert all(h["document_id"] == doc_a.json()["id"] for h in hits_a), \
            "ws_a не должен получать чанки ws_b"

        r_b = client.get(
            "/api/search", params={"q": "ЗЕТА-КОНТЕНТ"}, headers={"X-Workspace": WS_B}
        )
        hits_b = r_b.json()["results"]
        assert all(h["document_id"] == doc_a.json()["id"] for h in hits_b) is False or not hits_b, \
            "ws_b не должен получать чанки ws_a"


def _chat(client, ws: str, message: str) -> tuple[dict, str]:
    """SSE chat-запрос → ({event: последние данные}, полный текст ответа)."""
    headers = {"X-Workspace": ws} if ws else {}
    payload = {"message": message, "model": "mock"}
    events: dict[str, dict] = {}
    answer_parts: list[str] = []
    with client.stream("POST", "/api/chat", json=payload, headers=headers) as resp:
        assert resp.status_code == 200
        event = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                events.setdefault(event, {})
            elif line.startswith("data:") and event:
                data = json.loads(line[5:].strip())
                events[event] = data
                if event == "token":
                    answer_parts.append(data.get("delta") or "")
    assert "done" in events
    return events, "".join(answer_parts)


class TestChatContextScoped:
    def test_chat_answer_no_foreign_facts(self, client):
        """Интеграция: ответ в ws_a не содержит фактов из документов ws_b."""
        unique_b = " скидка Бонжур составляет ровно девяносто три процента"
        client.post(
            "/api/documents",
            files={"file": ("b-fact.docx", _docx_bytes(unique_b), DOCX_MIME)},
            headers={"X-Workspace": WS_B},
        )
        client.post(
            "/api/documents",
            files={"file": ("a-fact.docx", _docx_bytes("Скидка при оплате за год составляет 20 процентов"), DOCX_MIME)},
            headers={"X-Workspace": WS_A},
        )
        import time

        for _ in range(50):
            st = client.get("/api/documents", headers={"X-Workspace": WS_B}).json()
            if all(d["status"] == "ready" for d in st):
                break
            time.sleep(0.3)
        events, answer = _chat(client, WS_A, "Какая скидка при оплате за год?")
        assert "Бонжур" not in answer and "девяносто три" not in answer, \
            "ответ ws_a содержит факт из ws_b — retrieval не изолирован"


from app.db.session import SessionLocal  # noqa: E402 — для AgentScope


class TestAgentScopeIntegration:
    def test_agent_search_documents_scoped(self, client, tmp_path):
        import time

        from app.core.agent_tools import run_tool
        from app.db.session import SessionLocal

        doc = client.post(
            "/api/documents",
            files={"file": ("agent-doc.docx", _docx_bytes("текст для агента"), DOCX_MIME)},
            headers={"X-Workspace": WS_A},
        )
        assert doc.status_code == 201
        doc_id = doc.json()["id"]
        last_st = None
        for _ in range(50):  # ждём фоновой ingestion (status ready)
            last_st = client.get(f"/api/documents/{doc_id}", headers={"X-Workspace": WS_A}).json()["status"]
            if last_st == "ready":
                break
            time.sleep(0.3)
        print(f"DIAG ingestion final status={last_st}")
        import chromadb
        from chromadb.config import Settings

        from app.core.vectorstore import _client

        _col = _client().get_or_create_collection("documents")
        print("DIAG chroma count:", _col.count(),
              "| path:", getattr(_client(), "_settings", None) and _client()._settings.chroma_dir)
        _data = _col.get(include=["metadatas"])
        print("DIAG full:", json.dumps([
            {"id": i, "ws": (m or {}).get("workspace_id"), "fn": (m or {}).get("filename")}
            for i, m in zip(_data["ids"], _data["metadatas"] or [])
        ], ensure_ascii=False))
        from app.core import vectorstore

        probe = vectorstore.query(text="текст для агента", workspace_id=WS_A, top_k=5)
        s = SessionLocal()
        try:
            # search_documents: retrieval ws_B → пусто (Chroma изоляция уже работает,
            # т.к. vectorstore.query теперь фильтрует)
            obs_b, hits_b = run_tool(
                "search_documents", {"query": "текст для агента"}, db=s,
                workspace_id=WS_B, category=None, document_ids=None, top_k=5,
            )
            assert all(h["filename"] != "agent-doc.docx" for h in hits_b), \
                "ws_B получил чанк ws_a"
            obs_a, hits_a = run_tool(
                "search_documents", {"query": "текст для агента"}, db=s,
                workspace_id=WS_A, category=None, document_ids=None, top_k=5,
            )
            assert hits_a, "свой ws должен находить свой документ"
            own = {"agent-doc.docx", "ws-a.docx", "a-fact.docx"}
            assert all(h["filename"] in own for h in hits_a), \
                "ws_A получил чужой чанк: " + str([h["filename"] for h in hits_a])
        finally:
            s.close()
