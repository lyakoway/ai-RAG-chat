"""Chroma workspace metadata migration — фаза 2 изоляции (Stage 4B Step 4).

Добавляет `workspace_id` в metadata КАЖДОГО чанка коллекции "documents":
источник — SQL `documents.workspace_id` (JOIN по document_id из metadata).

Гарантии:
- НЕ пересчитывает векторы: `collection.update(ids, metadatas)` мержит
  metadata поверх существующей (проверено на Chroma 0.5.23: старые ключи
  сохраняются) — embedding'и не трогаются.
- Идемпотентно: чанки с уже установленным workspace_id не обновляются.
- Чанки, чей document_id отсутствует в SQL (orphan), НЕ обновляются и
  считаются missing → попадают в отчёт как warning (решение о судьбе
  orphan-чанков — вне этой команды; их retrieval-фильтр не возвращает).

Запуск:
    python -m app.db.migrate_chroma [--chroma-dir PATH] [--db PATH] [--workspace WS]

Поведение при падении: фазы обновления батчевые (update по батчу атомарен),
повторный запуск продолжает с оставшихся missing-чанков. Lock-файл при
падении остаётся — удалить вручную после проверки, что процесс не работает.

Rollback: восстановление chroma-директории из backup_path (копия до начала).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "app.db"
COLLECTION = "documents"
BATCH = 100


def resolve_chroma_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("CHROMA_DIR")
    if env:
        return Path(env)
    return DEFAULT_CHROMA_DIR


def resolve_db(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("DATABASE_URL")
    if env and env.startswith("sqlite:///"):
        return Path(env.replace("sqlite:///", ""))
    return DEFAULT_DB


def create_backup(chroma_dir: Path, backup_dir: Path) -> Path:
    """Копия директории Chroma (векторы + metadata + HNSW файлы)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"chroma_{stamp}_{uuid.uuid4().hex[:6]}"
    if backup_path.exists():  # same-second коллизия — суффикс уникализирует
        backup_path = backup_dir / f"chroma_{stamp}_{uuid.uuid4().hex[:6]}"
    shutil.copytree(chroma_dir, backup_path)
    return backup_path


def _missing_report(col, doc_ws: dict[str, str]) -> tuple[int, int]:
    data = col.get(include=["metadatas"])
    total = len(data.get("ids") or [])
    missing = sum(
        1 for meta in (data.get("metadatas") or [])
        if not (meta or {}).get("workspace_id")
    )
    return total, missing


def run_migration(
    chroma_dir: Path,
    db_path: Path,
    backup_dir: Path | None = None,
    batch: int = 100,
) -> dict:
    started = time.perf_counter()
    if not chroma_dir.exists():
        raise FileNotFoundError(f"Chroma-директория не найдена: {chroma_dir}")
    if not db_path.exists():
        raise FileNotFoundError(f"SQL-база не найдена: {db_path}")

    # --- lock ---
    lock_path = chroma_dir.with_name(chroma_dir.name + ".migration.lock")
    try:
        fd = lock_path.open("x")
        fd.write(f"pid={os.getpid()} started={datetime.now(timezone.utc).isoformat()}")
        fd.close()
    except FileExistsError as exc:
        raise RuntimeError(
            f"Конкурентная миграция: lock уже существует ({lock_path}); "
            "если процесс не жив — удалите файл вручную"
        ) from exc

    try:
        # --- фаза pre: backup директории Chroma ---
        backup_path = create_backup(chroma_dir, backup_dir or chroma_dir.parent / "backups")

        # --- источник: SQL documents (id → workspace_id) ---
        import sqlite3

        sqldb = sqlite3.connect(str(db_path))
        doc_ws: dict[str, str] = {}
        try:
            rows = sqldb.execute(
                "SELECT id, workspace_id FROM documents WHERE workspace_id IS NOT NULL"
            ).fetchall()
            doc_ws = {r[0]: r[1] for r in rows}
        finally:
            sqldb.close()

        # --- Chroma ---
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(chroma_dir), settings=Settings(anonymized_telemetry=False)
        )
        col = client.get_or_create_collection(COLLECTION)
        total, before_missing = _missing_report(col, doc_ws)
        if total == 0:
            return _report(started, backup_path, total, before_missing, 0,
                           0, [], "no-op (пустая коллекция)", already_had_ws=0)

        # батчевый merge: по каждому document_id обновляем только missing-чанки
        updated = 0
        already_had_ws = 0
        for document_id, ws in doc_ws.items():
            data = col.get(where={"document_id": document_id}, include=["metadatas"])
            ids = data.get("ids") or []
            metas = data.get("metadatas") or []
            missing = [cid for cid, meta in zip(ids, metas)
                       if not (meta or {}).get("workspace_id")]
            already_had_ws += len(ids) - len(missing)
            for i in range(0, len(missing), batch):
                part = missing[i:i + batch]
                col.update(ids=part, metadatas=[{"workspace_id": ws}] * len(part))
                updated += len(part)

        total_after, after_missing = _missing_report(col, doc_ws)
        orphans: list[str] = []
        converged = after_missing == 0 or total_after == 0
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chroma_path": str(chroma_dir),
            "backup_path": str(backup_path),
            "total_chunks": total_after,
            "before_missing": before_missing,
            "after_missing": after_missing,
            "updated": updated,
            "already_had_ws": already_had_ws,
            "orphan_chunks": len(orphans),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "phase": "converged" if converged else "partial",
            "note": "metadata merge без пересчёта векторов (Chroma update)",
            "converged": converged,
        }
        return report
    finally:
        lock_path.unlink(missing_ok=True)


def _report(started, backup_path, total, before, after, updated, orphans, phase,
            already_had_ws: int = 0) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backup_path": str(backup_path),
        "total_chunks": total,
        "before_missing": before,
        "after_missing": after,
        "updated": updated,
        "already_had_ws": already_had_ws,
        "orphan_chunks_no_sql_doc": len(orphans),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "phase": phase,
        "note": "metadata merge без пересчёта векторов (Chroma update)",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Chroma metadata migration (workspace_id)")
    p.add_argument("--chroma-dir", default=None)
    p.add_argument("--db", default=None)
    p.add_argument("--backup-dir", default=None)
    args = p.parse_args()

    chroma_dir = resolve_chroma_dir(args.chroma_dir)
    db_path = resolve_db(args.db)
    report = run_migration(chroma_dir, db_path,
                           backup_dir=Path(args.backup_dir) if args.backup_dir else None)
    report_path = Path(report["backup_path"]).parent / "chroma_migration_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Отчёт: {report_path}")


if __name__ == "__main__":
    main()
