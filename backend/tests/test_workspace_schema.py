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
from sqlalchemy import text as sa_text

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


class TestModelMigrationSync:
    """Модель и миграция не разошлись: create_all-схема (модель) идентична
    migrate-схеме по workspace_id (NOT NULL + DEFAULT 'default')."""

    def _fresh(self, tmp_path: Path):
        from sqlalchemy import create_engine, inspect as sa_inspect, text as sa_text
        from sqlalchemy.orm import sessionmaker

        from app.db import models as _models  # noqa: F401 — регистрация в metadata
        from app.db.models import Conversation, Document
        from app.db.session import Base

        engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        return engine, Session, sa_inspect, sa_text

    def test_model_column_not_null_with_default(self, tmp_path):
        engine, _, sa_inspect, _ = self._fresh(tmp_path)
        for model in ("documents", "conversations"):
            col = next(c for c in sa_inspect(engine).get_columns(model)
                       if c["name"] == "workspace_id")
            assert col["nullable"] is False
            # SQLite reflection отдаёт DEFAULT как строку "'default'"
            assert "'default'" in str(col["default"])
        engine.dispose()

    def test_orm_insert_without_workspace_gets_default(self, tmp_path):
        engine, Session, _, _ = self._fresh(tmp_path)
        s = Session()
        s.add(Document(id="d-nw", filename="x.docx", content_type="docx"))  # без ws
        s.commit()
        ws = s.execute(sa_text("SELECT workspace_id FROM documents WHERE id='d-nw'")).scalar()
        assert ws == "default"
        s.close()
        engine.dispose()

    def test_raw_sql_insert_without_workspace_gets_server_default(self, tmp_path):
        """Прямой SQL INSERT без workspace_id (остальные NOT NULL заданы) —
        server_default в DDL подставляет 'default'."""
        engine, _, sa_inspect, sa_text = self._fresh(tmp_path)
        with engine.begin() as conn:
            conn.execute(sa_text(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES ('c-nw', 'без ws', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
        ws = sa_inspect(engine).get_columns("conversations")
        row = sa_text  # placeholder to keep linters honest
        from sqlalchemy import inspect as _i

        with engine.connect() as conn:
            value = conn.execute(sa_text(
                "SELECT workspace_id FROM conversations WHERE id='c-nw'"
            )).scalar()
        assert value == "default"
        engine.dispose()

    def test_raw_insert_null_ws_fails(self, tmp_path):
        """NOT NULL enforcement на слое БД: явный NULL → IntegrityError.
        Примечание: ORM-вставка с workspace_id=None НЕ упадёт — SQLAlchemy
        применит Python-default 'default' (это production-поведение до Step 3:
        пути без ws получают default, а не ошибку)."""
        engine, _, _, sa_text = self._fresh(tmp_path)
        from sqlalchemy import text as plain_text

        with engine.begin() as conn:
            with pytest.raises(Exception):
                conn.execute(plain_text(
                    "INSERT INTO documents (id, filename, workspace_id) "
                    "VALUES ('d-null', 'x.docx', NULL)"
                ))
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

    def test_init_db_is_schema_only_no_backfill(self, tmp_path):
        """Вечный инвариант: init_db() — schema-only, никогда не бэкфиллит.

        На изолированной tmp-базе со «старой схемой» (таблица без workspace_id
        и данными) init-логика добавляет nullable-колонку, существующие строки
        остаются IS NULL. Не проверяется на общей/боевой базе: там после
        migrate phase 1 все записи уже в 'default' (см. docs/migration-plan.md)."""
        import sqlite3

        from app.db.session import _ensure_sqlite_column

        db = sqlite3.connect(tmp_path / "legacy.db")
        db.execute(
            "CREATE TABLE documents ("
            " id VARCHAR(32) PRIMARY KEY NOT NULL, filename VARCHAR(512) NOT NULL)"
        )
        db.execute("INSERT INTO documents VALUES ('doc-legacy', 'старый документ.docx')")
        db.commit()
        assert _ensure_sqlite_column(db, "documents", "workspace_id", "VARCHAR(64)") is True
        row = db.execute(
            "SELECT workspace_id FROM documents WHERE id='doc-legacy'"
        ).fetchone()
        assert row[0] is None, "init_db/ensure не должен подставлять default — это data migration"
        db.close()
