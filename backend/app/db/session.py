"""SQLAlchemy engine / session setup (SQLite)."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Schema-only initialization.

    Создаёт таблицы/индексы и добавляет недостающие колонки. Данные НЕ
    трогает: data migration (backfill workspace_id, Chroma metadata, файлы)
    — отдельная команда app/db/migrate.py (Stage 4B Step 3).
    """
    # Import models so they are registered on Base before create_all.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _ensure_sqlite_column(conn, "messages", "agent_steps", "JSON")
        _ensure_sqlite_column(conn, "documents", "lang", "VARCHAR(8)")
        _ensure_sqlite_column(conn, "documents", "pair_key", "VARCHAR(64)")
        _ensure_sqlite_column(conn, "messages", "feedback", "VARCHAR(8)")
        _ensure_sqlite_column(conn, "documents", "workspace_id", "VARCHAR(64)")
        _ensure_sqlite_column(conn, "conversations", "workspace_id", "VARCHAR(64)")
        # Имена совпадают с автонеймингом SQLAlchemy (ix_<table>_<column>),
        # чтобы fresh- и migrated-схемы были идентичны.
        _ensure_sqlite_index(conn, "ix_documents_workspace_id", "documents", ["workspace_id"])
        _ensure_sqlite_index(conn, "ix_conversations_workspace_id", "conversations", ["workspace_id"])


def _rows(conn, sql: str) -> list[tuple]:
    """Duck-typed fetchall: SQLAlchemy Connection (exec_driver_sql) или
    sqlite3.Connection (execute) — для изолированных schema-тестов."""
    if hasattr(conn, "exec_driver_sql"):
        return conn.exec_driver_sql(sql).fetchall()
    return conn.execute(sql).fetchall()


def _ensure_sqlite_column(conn, table: str, column: str, col_type: str) -> bool:
    """Add a column to an existing SQLite table (create_all does not alter).

    Принимает любой connection с exec_driver_sql (SQLAlchemy Connection или
    sqlite3.Connection) — позволяет изолированным тестам проверять логику
    на отдельной базе. Колонка добавляется nullable: SQLite отклоняет
    ADD COLUMN … NOT NULL без DEFAULT (проверено на 3.x); NOT NULL
    устанавливает миграция после backfill. Возвращает True, если добавлена.
    """
    if not settings.database_url.startswith("sqlite"):
        return False
    rows = _rows(conn, f"PRAGMA table_info({table})")
    if not rows:
        return False  # таблицы ещё нет — её создаст create_all
    names = {r[1] for r in rows}
    if column in names:
        return False
    if hasattr(conn, "exec_driver_sql"):
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    else:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    return True


def _ensure_sqlite_index(conn, index_name: str, table: str, columns: list[str]) -> bool:
    """CREATE INDEX IF NOT EXISTS для существующих таблиц (для новых таблиц
    индекс создаёт create_all по index=True). Возвращает True, если создан."""
    if not settings.database_url.startswith("sqlite"):
        return False
    tables = {r[0] for r in _rows(conn, "SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in tables:
        return False
    # PRAGMA index_list: колонка 1 — имя индекса (колонка 0 — порядковый номер).
    indexes = {r[1] for r in _rows(conn, f"PRAGMA index_list({table})")}
    if index_name in indexes:
        return False
    sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({', '.join(columns)})"
    if hasattr(conn, "exec_driver_sql"):
        conn.exec_driver_sql(sql)
    else:
        conn.execute(sql)
    return True
