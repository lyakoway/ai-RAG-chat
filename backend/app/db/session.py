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
    # Import models so they are registered on Base before create_all.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_column("messages", "agent_steps", "JSON")
    _ensure_sqlite_column("documents", "lang", "VARCHAR(8)")
    _ensure_sqlite_column("documents", "pair_key", "VARCHAR(64)")
    _ensure_sqlite_column("messages", "feedback", "VARCHAR(8)")


def _ensure_sqlite_column(table: str, column: str, col_type: str) -> None:
    """Add a column to existing SQLite tables (create_all does not alter)."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        names = {r[1] for r in rows}
        if column not in names:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
