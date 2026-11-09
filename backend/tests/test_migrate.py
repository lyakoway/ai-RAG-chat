"""Stage 4B Step 3: тесты migrate.py фазы 1.

Каждый тест работает на изолированной tmp-базе (боевая база не затрагивается);
run_migration создаёт backup в tmp и возвращает отчёт.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import migrate as m


def _make_db(path: Path, *, conversations: bool = True, null_ws: bool = True) -> None:
    """Старая схема (nullable ws, как после Step 2) с данными."""
    db = sqlite3.connect(str(path))
    db.execute(
        "CREATE TABLE documents ("
        " id VARCHAR(32) PRIMARY KEY NOT NULL, filename VARCHAR(512) NOT NULL,"
        " workspace_id VARCHAR(64))"
    )
    if conversations:
        db.execute(
            "CREATE TABLE conversations ("
            " id VARCHAR(32) PRIMARY KEY NOT NULL, title VARCHAR(512) NOT NULL,"
            " workspace_id VARCHAR(64))"
        )
        db.execute(
            "CREATE TABLE messages ("
            " id VARCHAR(32) PRIMARY KEY NOT NULL,"
            " conversation_id VARCHAR(32) NOT NULL REFERENCES conversations(id),"
            " role VARCHAR(16) NOT NULL, content TEXT NOT NULL)"
        )
    rows_docs = [("d1", "a.docx"), ("d2", "b.pdf")] if null_ws else \
                [("d1", "a.docx"), ("d2", "b.pdf")]
    for did, fname in rows_docs:
        ws = "NULL" if null_ws else "'ws-keep'"
        db.execute(
            f"INSERT INTO documents VALUES ('{did}', '{fname}', {ws})"
        )
    if conversations:
        db.execute("INSERT INTO conversations VALUES ('c1', 'Диалог 1', NULL)")
        db.execute(
            "INSERT INTO messages VALUES ('m1', 'c1', 'user', 'вопрос')"
        )
    db.commit()
    db.close()


def _ws_column(db: sqlite3.Connection, table: str) -> dict:
    col = next(c for c in db.execute(f"PRAGMA table_info({table})").fetchall()
               if c[1] == "workspace_id")
    return {"notnull": bool(col[3]), "default": col[4]}


class TestBackfill:
    def test_null_backfilled_to_default_both_tables(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        m.run_migration(db_path)
        db = sqlite3.connect(str(db_path))
        for t in ("documents", "conversations"):
            nulls = db.execute(f"SELECT COUNT(*) FROM {t} WHERE workspace_id IS NULL").fetchone()[0]
            assert nulls == 0, t
            values = {r[0] for r in db.execute(f"SELECT DISTINCT workspace_id FROM {t}")}
            assert values == {"default"}
        db.close()


class TestNotNullEnforcement:
    def test_insert_without_workspace_gets_default(self, tmp_path):
        """После migrate: NOT NULL + DEFAULT 'default'. Прямой SQL INSERT без
        workspace_id получает 'default' — доказательство синхронности
        DDL миграции и server_default модели (docs/migration-plan.md)."""
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        m.run_migration(db_path)
        db = sqlite3.connect(str(db_path))
        assert _ws_column(db, "documents")["notnull"] is True
        assert "'default'" in str(_ws_column(db, "documents")["default"])
        assert _ws_column(db, "conversations")["notnull"] is True
        db.execute("INSERT INTO documents (id, filename) VALUES ('d3', 'x.docx')")
        ws = db.execute("SELECT workspace_id FROM documents WHERE id='d3'").fetchone()[0]
        assert ws == "default", "server_default должен сработать на прямом SQL INSERT"
        db.close()


class TestIdempotency:
    def test_second_run_is_noop(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        m.run_migration(db_path)
        db = sqlite3.connect(str(db_path))
        before = db.execute("SELECT * FROM documents ORDER BY id").fetchall()
        db.close()
        report = m.run_migration(db_path)
        assert report["phase"].startswith("no-op")
        db = sqlite3.connect(str(db_path))
        assert db.execute("SELECT * FROM documents ORDER BY id").fetchall() == before
        assert report["before_null_count"] == 0 and report["after_null_count"] == 0
        db.close()


class TestBackup:
    def test_backup_created_and_valid(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        backup_dir = tmp_path / "backups"
        m.run_migration(db_path, backup_dir=backup_dir)
        backups = list(backup_dir.glob("app_*.db"))
        assert len(backups) == 1
        ro = sqlite3.connect(f"file:{backups[0]}?mode=ro", uri=True)
        assert ro.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # backup — состояние ДО миграции: ws nullable и NULL
        assert _ws_column(ro, "documents")["notnull"] is False
        assert ro.execute("SELECT COUNT(*) FROM documents WHERE workspace_id IS NULL").fetchone()[0] == 2
        ro.close()


class TestRebuildPreservesData:
    def test_fields_and_messages_preserved(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        m.run_migration(db_path)
        db = sqlite3.connect(str(db_path))
        docs = db.execute("SELECT id, filename, workspace_id FROM documents ORDER BY id").fetchall()
        assert docs == [("d1", "a.docx", "default"), ("d2", "b.pdf", "default")]
        convs = db.execute("SELECT id, title, workspace_id FROM conversations").fetchall()
        assert convs == [("c1", "Диалог 1", "default")]
        msgs = db.execute("SELECT id, conversation_id, role, content FROM messages").fetchall()
        assert msgs == [("m1", "c1", "user", "вопрос")]
        db.close()

    def test_related_message_insert_after_rebuild(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        m.run_migration(db_path)
        db = sqlite3.connect(str(db_path))
        db.execute("INSERT INTO messages VALUES ('m2', 'c1', 'assistant', 'ответ')")
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        db.close()


class TestFailureRollback:
    def test_injected_failure_rolls_back_transaction(self, tmp_path, monkeypatch):
        """Падение посреди rebuild: транзакция откатывается — данные целы,
        колонка остаётся nullable (NOT NULL не применился), ws не заполнен."""
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        with pytest.raises(RuntimeError, match="injected failure"):
            m.run_migration(db_path, _fail_after_table="documents")
        db = sqlite3.connect(str(db_path))
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert _ws_column(db, "documents")["notnull"] is False
        # backfill был в той же транзакции — тоже откатился
        assert db.execute(
            "SELECT COUNT(*) FROM documents WHERE workspace_id IS NULL"
        ).fetchone()[0] == 2
        db.close()


class TestForeignKeyCheck:
    def test_foreign_key_check_ok_after_migration(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        report = m.run_migration(db_path)
        assert report["foreign_key_check_ok"] is True

    def test_foreign_key_check_detects_orphans(self, tmp_path):
        """Sanity: foreign_key_check находит orphan. Вставка при foreign_keys=OFF
        (текущее поведение рантайма), затем включаем FK и проверяем."""
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        m.run_migration(db_path)
        db = sqlite3.connect(str(db_path))
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("INSERT INTO messages VALUES ('m-orphan', 'no-such-conv', 'user', 'x')")
        db.commit()
        db.execute("PRAGMA foreign_keys=ON")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        assert violations, "orphan должен детектироваться"
        db.close()


class TestLockAndReport:
    def test_lock_blocks_concurrent_run(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        lock = db_path.with_name(db_path.name + ".migration.lock")
        lock.write_text("pid=999999")
        with pytest.raises(RuntimeError, match="lock"):
            m.run_migration(db_path)
        lock.unlink()
        m.run_migration(db_path)  # после снятия lock — работает

    def test_report_fields(self, tmp_path):
        db_path = tmp_path / "app.db"
        _make_db(db_path)
        report = m.run_migration(db_path)
        for field in ("timestamp", "backup_path", "before_null_count",
                      "after_null_count", "foreign_key_check_ok", "duration_ms"):
            assert field in report
        assert report["before_null_count"] == 3  # 2 documents + 1 conversation
        assert report["after_null_count"] == 0
