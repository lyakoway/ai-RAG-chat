"""Stage 4B Step 2: SQL workspace schema — модели, init_db (schema-only).

Сценарии на изолированной tmp-базе проверяют поведение на «существующей
схеме» (таблица без workspace_id + данные) — глобальный test store для этого
не подходит, т.к. его схема уже актуальна. Хелперы session.py duck-typed
(exec_driver_sql) и принимают sqlite3.Connection напрямую.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from app.db.models import Conversation, Document, Message
from app.db.session import (
    Base,
    _ensure_sqlite_column,
    _ensure_sqlite_index,
    init_db,
)


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _indexes(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f"PRAGMA index_list({table})").fetchall()}


class TestIsolatedSchema:
    """Старая схема (без workspace_id) + данные → хелперы/init-логика."""

    def _old_db(self, tmp_path: Path) -> sqlite3.Connection:
        db = sqlite3.connect(tmp_path / "old.db")
        db.execute(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT, lang TEXT)"
        )
        db.execute("INSERT INTO documents VALUES ('doc-old', 'старый документ.docx', 'ru')")
        db.commit()
        return db

    def test_ensure_column_added_nullable(self, tmp_path):
        db = self._old_db(tmp_path)
        added = _ensure_sqlite_column(db, "documents", "workspace_id", "VARCHAR(64)")
        assert added is True
        assert "workspace_id" in _columns(db, "documents")
        # nullable: SQLite NOT NULL без DEFAULT отклоняется (проверено на 3.x) —
        # колонка добавляется без constraint, backfill делает миграция.
        row = db.execute("SELECT workspace_id FROM documents").fetchone()
        assert row[0] is None, "schema-only init не подставляет default"

    def test_ensure_column_idempotent(self, tmp_path):
        db = self._old_db(tmp_path)
        _ensure_sqlite_column(db, "documents", "workspace_id", "VARCHAR(64)")
        assert _ensure_sqlite_column(db, "documents", "workspace_id", "VARCHAR(64)") is False

    def test_ensure_column_skips_missing_table(self, tmp_path):
        db = sqlite3.connect(tmp_path / "empty.db")
        assert _ensure_sqlite_column(db, "no_such_table", "workspace_id", "VARCHAR(64)") is False

    def test_ensure_index_created_and_idempotent(self, tmp_path):
        db = self._old_db(tmp_path)
        _ensure_sqlite_column(db, "documents", "workspace_id", "VARCHAR(64)")
        assert _ensure_sqlite_index(db, "ix_documents_workspace_id", "documents", ["workspace_id"]) is True
        assert "ix_documents_workspace_id" in _indexes(db, "documents")
        assert _ensure_sqlite_index(db, "ix_documents_workspace_id", "documents", ["workspace_id"]) is False

    def test_ensure_index_skips_missing_table(self, tmp_path):
        db = sqlite3.connect(tmp_path / "empty2.db")
        assert _ensure_sqlite_index(db, "ix_x", "no_such_table", ["workspace_id"]) is False

    def test_existing_data_preserved_and_not_backfilled(self, tmp_path):
        """schema-only: существующая запись сохраняет данные, workspace_id
        остаётся NULL (backfill — миграция, не init_db)."""
        db = self._old_db(tmp_path)
        _ensure_sqlite_column(db, "documents", "workspace_id", "VARCHAR(64)")
        name, ws = db.execute(
            "SELECT filename, workspace_id FROM documents WHERE id='doc-old'"
        ).fetchone()
        assert name == "старый документ.docx"
        assert ws is None


class TestModelsWorkspace:
    def test_document_and_conversation_have_workspace_column(self, tmp_path):
        from sqlalchemy import create_engine

        from app.db.session import SessionLocal

        # create_all на чистой tmp-базе: схему моделей создаёт Base.metadata.
        engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
        Base.metadata.create_all(bind=engine)
        columns = _columns(sqlite3.connect(tmp_path / "models.db"), "documents")
        assert "workspace_id" in columns
        assert "workspace_id" in _columns(sqlite3.connect(tmp_path / "models.db"), "conversations")
        engine.dispose()
        _ = SessionLocal  # сессия проекта не нужна для этого теста

    def test_indexes_on_fresh_schema(self, tmp_path):
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        Base.metadata.create_all(bind=engine)
        idx = _indexes(sqlite3.connect(tmp_path / "fresh.db"), "documents")
        assert "ix_documents_workspace_id" in idx
        assert "ix_conversations_workspace_id" in _indexes(
            sqlite3.connect(tmp_path / "fresh.db"), "conversations"
        )
        engine.dispose()

    def test_workspace_id_saved_on_new_records(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(f"sqlite:///{tmp_path / 'save.db'}")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        s = Session()
        conv = Conversation(id="c1", title="t", workspace_id="ws-t")
        s.add(conv)
        s.add(Document(id="d1", filename="f.docx", content_type="docx",
                       workspace_id="ws-t"))
        s.commit()
        assert s.get(Document, "d1").workspace_id == "ws-t"
        assert s.get(Conversation, "c1").workspace_id == "ws-t"
        s.close()
        engine.dispose()

    def test_message_has_no_workspace_field(self):
        """Message не имеет дублирующего workspace_id — наследует через
        родительскую Conversation."""
        assert not hasattr(Message, "workspace_id")

    def test_message_belongs_to_conversation(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(f"sqlite:///{tmp_path / 'msg.db'}")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        s = Session()
        conv = Conversation(id="c2", title="t", workspace_id="ws-t")
        s.add(conv)
        s.flush()
        msg = Message(id="m1", conversation_id="c2", role="user", content="hi")
        s.add(msg)
        s.commit()
        assert msg.conversation.workspace_id == "ws-t"
        s.close()
        engine.dispose()


class TestInitDbIdempotent:
    def test_repeated_init_db_preserves_data(self, client, demo_loaded):
        """Повторный init_db() на test store: схема идемпотентна, существующие
        записи (демо-документы) не изменяются и не дублируются."""
        from sqlalchemy import select

        from app.db.models import Document
        from app.db.session import init_db

        before = client.get("/api/documents").json()
        init_db()
        after = client.get("/api/documents").json()
        assert len(after) == len(before)
        assert {d["id"] for d in after} == {d["id"] for d in before}
        # повторный вызов не меняет записи
        docs = client.get("/api/documents").json()
        assert all(d["filename"] for d in docs)

    def test_init_db_does_not_backfill_workspace(self, client, demo_loaded):
        """schema-only: init_db не подставляет default и не трогает
        workspace_id существующих записей (data migration — отдельная команда)."""
        from sqlalchemy import select

        from app.db.models import Document
        from app.db.session import SessionLocal, init_db

        s = SessionLocal()
        ids = s.scalars(select(Document.id)).all()
        init_db()
        for doc_id in ids:
            row = s.execute(
                select(Document.workspace_id).where(Document.id == doc_id)
            ).scalar()
            assert row is None, f"{doc_id}: init_db подставил workspace_id — это data migration"
        s.rollback()
        s.close()
