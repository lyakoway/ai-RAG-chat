"""Workspace isolation migration — фаза 1: backfill + rebuild + NOT NULL.

Приводит documents.workspace_id и conversations.workspace_id к NOT NULL с
backfillом NULL → 'default' (см. docs/migration-plan.md, docs/STAGE_4B_PLAN.md).

Запуск:
    python -m app.db.migrate [--db PATH] [--workspace WS] [--backup-dir DIR]
    (по умолчанию PATH = settings.database_url, WS = "default")

Фазы (идемпотентно):
  pre  — lock + backup: PRAGMA wal_checkpoint(TRUNCATE) на исходной базе,
         копия app.db (+ -wal/-shm при наличии), backup открывается
         read-only и проверяется PRAGMA integrity_check; не 'ok' → fail.
  1    — ЕДИНАЯ транзакция BEGIN IMMEDIATE:
         backfill UPDATE … SET workspace_id=:ws WHERE workspace_id IS NULL,
         rebuild documents/conversations (CREATE new с NOT NULL → INSERT
         SELECT → DROP old → ALTER RENAME → пересоздание индексов по
         sqlite_master.sql).
  post — PRAGMA foreign_key_check + NULL count = 0 → отчёт JSON
         (timestamp, backup_path, before_null_count, after_null_count,
         foreign_key_check_ok, duration_ms, tables).

Идемпотентность: таблица считается обработанной, если workspace_id has
notnull=1 (PRAGMA table_info) и NULL count = 0 — повторный запуск no-op.

Rollback при падении: фаза 1 в одной транзакции — при исключении ROLLBACK
возвращает базу к исходному состоянию (данные не теряются; backfill тоже
откатывается). После успешного COMMIT откат возможен только восстановлением
из backup_path (см. report). Lock-файл при падении удалять вручную.

Ограничение SQLite (проверено): ALTER TABLE ADD COLUMN … NOT NULL без DEFAULT
отклоняется; поэтому nullable-колонки Step 2 — переходное состояние, NOT NULL
появляется только через rebuild.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_WORKSPACE = "default"


def _ws_id(value: str) -> str:
    """Валидация workspace_id — та же схема, что в app/config.py
    (regex дублируется намеренно: migrate CLI не зависит от app/config)."""
    if not value or not re.fullmatch(r"[a-z0-9_-]{1,64}", value):
        raise ValueError(f"workspace_id {value!r} не соответствует формату")
    return value


def _rows(conn, sql: str) -> list[tuple]:
    """Duck-typed fetchall (SQLAlchemy Connection или sqlite3.Connection)."""
    if hasattr(conn, "exec_driver_sql"):
        return conn.exec_driver_sql(sql).fetchall()
    return conn.execute(sql).fetchall()


def _ensure_sqlite_column(conn: sqlite3.Connection, table: str,
                          column: str, col_type: str) -> bool:
    rows = _rows(conn, f"PRAGMA table_info({table})")
    if not rows:
        return False
    if column in {r[1] for r in rows}:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    return True


def _ensure_sqlite_index(conn: sqlite3.Connection, index_name: str,
                         table: str, columns: list[str]) -> bool:
    indexes = {r[1] for r in _rows(conn, f"PRAGMA index_list({table})")}
    if index_name in indexes:
        return False
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({', '.join(columns)})"
    )
    return True


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    """wal_checkpoint(TRUNCATE) → копия db (+wal/shm) → read-only
    integrity_check. Fail при не-ok или отсутствии файла."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{db_path.stem}_{stamp}{db_path.suffix}"

    src = sqlite3.connect(str(db_path))
    try:
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        src.close()

    shutil.copy2(db_path, backup_path)
    for suffix in ("-wal", "-shm"):
        extra = db_path.with_name(db_path.name + suffix)
        if extra.exists():
            shutil.copy2(extra, backup_path.with_name(backup_path.name + suffix))

    ro = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        result = ro.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        ro.close()
    if result != "ok":
        raise RuntimeError(f"backup integrity_check failed: {result!r} ({backup_path})")
    return backup_path


def _columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    return [
        {"name": r[1], "type": r[2] or "TEXT", "notnull": bool(r[3]), "pk": bool(r[5])}
        for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
    ]


def _null_count(conn: sqlite3.Connection, table: str, column: str = "workspace_id") -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
    ).fetchone()[0]


def _is_rebuilt(conn: sqlite3.Connection, table: str) -> bool:
    """Уже обработано: workspace_id has notnull=1 AND DEFAULT 'default' AND
    NULL count = 0. Отсутствие DEFAULT (базы, мигрированные до v1.1 DDL) —
    тоже причина повторного rebuild."""
    cols = _columns(conn, table)
    ws = next((c for c in cols if c["name"] == "workspace_id"), None)
    if ws is None or not ws["notnull"] or _null_count(conn, table) != 0:
        return False
    has_default = ws.get("default") is not None
    if not has_default:
        # не удалось прочитать dflt_value — считаем rebuilt (PRAGMA отдаёт строку)
        return True
    return "'default'" in str(ws["default"])


def _table_indexes(conn: sqlite3.Connection, table: str) -> list[str]:
    """CREATE-выражения именованных индексов таблицы (не autoindex)."""
    rows = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def _rebuild_table(conn: sqlite3.Connection, table: str) -> None:
    """CREATE new (NOT NULL на workspace_id) → INSERT SELECT → DROP old →
    RENAME → пересоздание индексов. Вызывается внутри транзакции фазы 1."""
    cols = _columns(conn, table)
    names = [c["name"] for c in cols]
    col_defs = []
    for c in cols:
        definition = f"{c['name']} {c['type']}"
        if c["pk"]:
            definition += " PRIMARY KEY"
        if c["name"] == "workspace_id":
            # NOT NULL + DEFAULT: синхронно с models.py (server_default),
            # чтобы прямой SQL INSERT без ws получал 'default' и на
            # уже мигрированной базе.
            definition += " NOT NULL DEFAULT 'default'"
        elif c["notnull"]:
            definition += " NOT NULL"
        col_defs.append(definition)
    conn.execute(f"CREATE TABLE {table}_new ({', '.join(col_defs)})")
    conn.execute(
        f"INSERT INTO {table}_new ({', '.join(names)}) "
        f"SELECT {', '.join(names)} FROM {table}"
    )
    index_sqls = _table_indexes(conn, table)
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
    for sql in index_sqls:
        conn.execute(sql)


def run_migration(
    db_path: Path,
    workspace: str = DEFAULT_WORKSPACE,
    backup_dir: Path | None = None,
    tables: tuple[str, ...] = ("documents", "conversations"),
    _fail_after_table: str | None = None,
) -> dict:
    columns_added: dict[str, bool] = {}
    """Фаза 1 целиком. _fail_after_table — тестовая инъекция исключения
    посреди транзакции (после обработки указанной таблицы)."""
    from app.config import validate_workspace_id

    ws = _ws_id(workspace)
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"База данных не найдена: {db_path}")
    backup_dir = backup_dir or db_path.parent / "backups"

    started = time.perf_counter()
    # --- lock: отказ при конкуренции; stale-файл удаляется вручную ---
    lock_path = db_path.with_name(db_path.name + ".migration.lock")
    try:
        lock_fd = lock_path.open("x")
        lock_fd.write(f"pid={__import__('os').getpid()} started={datetime.now(timezone.utc).isoformat()}")
        lock_fd.close()
    except FileExistsError as exc:
        raise RuntimeError(
            f"Конкурентная миграция: lock уже существует ({lock_path}); "
            "если процесс не жив — удалите файл вручную"
        ) from exc

    try:
        # --- фаза pre: backup + integrity ---
        backup_path = create_backup(db_path, backup_dir)

        conn = sqlite3.connect(str(db_path), isolation_level=None)  # явные транзакции
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            # Schema-prep: nullable-колонка может отсутствовать (базы, где
            # init_db не запускался после Step 2) — добавляем идемпотентно.
            for t in tables:
                columns_added[t] = _ensure_sqlite_column(
                    conn, t, "workspace_id", "VARCHAR(64)"
                )
            before_null = sum(_null_count(conn, t) for t in tables)
            already = all(_is_rebuilt(conn, t) for t in tables)
            if already and before_null == 0:
                report = _report(started, backup_path, before_null, 0, True,
                                 conn, tables, "no-op (already migrated)")
                return report

            # --- фаза 1: одна транзакция на backfill + rebuild ---
            conn.execute("BEGIN IMMEDIATE")
            try:
                for t in tables:
                    conn.execute(
                        f"UPDATE {t} SET workspace_id=:ws WHERE workspace_id IS NULL",
                        {"ws": ws},
                    )
                for t in tables:
                    _rebuild_table(conn, t)
                    # Индекс ws-колонки: в старых базах его может не быть;
                    # имя совпадает с автонеймингом SQLAlchemy (create_all).
                    _ensure_sqlite_index(conn, f"ix_{t}_workspace_id", t, ["workspace_id"])
                    if _fail_after_table == t:
                        raise RuntimeError("injected failure (test)")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            conn.execute("PRAGMA foreign_keys=ON")
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            fk_ok = not fk_violations
            after_null = sum(_null_count(conn, t) for t in tables)
            if after_null != 0:
                raise RuntimeError(f"после миграции остались NULL: {after_null}")

            report = _report(started, backup_path, before_null, after_null, fk_ok,
                             conn, tables, "migrated", columns_added)
            return report
        finally:
            conn.close()
    finally:
        lock_path.unlink(missing_ok=True)


def _report(started: float, backup_path: Path, before: int, after: int, fk_ok: bool,
            conn: sqlite3.Connection, tables: tuple[str, ...], phase: str,
            columns_added: dict[str, bool] | None = None) -> dict:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backup_path": str(backup_path),
        "before_null_count": before,
        "after_null_count": after,
        "foreign_key_check_ok": fk_ok,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "phase": phase,
        "tables": {
            t: {"null_count": _null_count(conn, t), "rebuilt": _is_rebuilt(conn, t)}
            for t in tables
        },
        "columns_added": columns_added or {},
    }
    return report


def resolve_db_path(explicit: str | None) -> Path:
    """Путь к БД для миграции. Операционный инструмент НЕ зависит от
    workspace-auth конфигурации (Settings), поэтому не использует get_settings:
    --db → env DATABASE_URL → дефолт backend/data/app.db."""
    if explicit:
        return Path(explicit)
    env_db = os.environ.get("DATABASE_URL")
    if env_db and env_db.startswith("sqlite:///"):
        return Path(env_db.replace("sqlite:///", ""))
    return Path(__file__).resolve().parent.parent / "data" / "app.db"


def main() -> None:
    p = argparse.ArgumentParser(description="Фаза 1: backfill + rebuild + NOT NULL")
    p.add_argument("--db", default=None, help="путь к SQLite (по умолчанию backend/data/app.db или DATABASE_URL)")
    p.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    p.add_argument("--backup-dir", default=None)
    args = p.parse_args()

    db_path = resolve_db_path(args.db)
    report = run_migration(db_path, workspace=args.workspace,
                           backup_dir=Path(args.backup_dir) if args.backup_dir else None)
    report_path = Path(report["backup_path"]).parent / "migration_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Отчёт: {report_path}")


if __name__ == "__main__":
    main()
