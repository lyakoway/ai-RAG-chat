"""Robustness evaluation: поведение retrieval на загрязнённом корпусе.

Сценарий: в чистый индекс демо-пака добавляются повреждённые и вырожденные
документы, затем проверяется:
  1. каждый «битый» файл либо чисто отклонён парсером, либо не добавил чанков;
  2. пайплайн не падает на запросах;
  3. Recall@1/3, MRR@5, nDCG@5 на golden set не деградировали против чистого
     прогона (тот же инстанс индекса, hybrid-конфигурация).

Это корпус-уровень: API-обработка битых загрузок уже покрыта тестами
(test_edge_cases.py), здесь проверяется влияние мусора, ПРОШЕДШЕГО приёмку,
на качество поиска для здоровых вопросов.

Запуск (из backend/):
    .venv/bin/python benchmarks/robustness_eval.py            # с артефактом
    .venv/bin/python benchmarks/robustness_eval.py --no-json  # быстрый прогон
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

EVAL_DIR = BASE / "data" / "eval"
os.environ["UPLOAD_DIR"] = str(EVAL_DIR / "uploads")
os.environ["CHROMA_DIR"] = str(EVAL_DIR / "chroma")
os.environ["DATABASE_URL"] = f"sqlite:///{EVAL_DIR / 'app.db'}"
os.environ["SEARCH_HYBRID"] = "1"

from benchmarks.metrics import (  # noqa: E402
    command_line,
    git_commit,
    iso_utc,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    save_results,
)


def make_pollutants(dir_path: Path) -> list[dict]:
    """Создаёт файлы-загрязнители четырёх типов и возвращает их описания."""
    dir_path.mkdir(parents=True, exist_ok=True)
    samples = BASE / "samples"
    out = []

    # 1) обрезанный валидный PDF (первые 200 байт живого файла)
    src = samples / "User_Guide.pdf"
    if src.exists():
        p = dir_path / "truncated.pdf"
        p.write_bytes(src.read_bytes()[:200])
        out.append({"file": "truncated.pdf", "kind": "truncated_pdf"})

    # 2) бинарный мусор с расширением .pdf
    p = dir_path / "junk.pdf"
    p.write_bytes(bytes(range(256)) * 8)
    out.append({"file": "junk.pdf", "kind": "binary_junk"})

    # 3) пустой .docx (0 байт)
    p = dir_path / "empty.docx"
    p.write_bytes(b"")
    out.append({"file": "empty.docx", "kind": "empty_docx"})

    # 4) валидный docx только из пробелов/пустых параграфов (пройдёт парсер)
    try:
        from docx import Document

        doc = Document()
        for _ in range(5):
            doc.add_paragraph("   \n\t  ")
        p = dir_path / "whitespace.docx"
        doc.save(str(p))
        out.append({"file": "whitespace.docx", "kind": "whitespace_only_docx"})
    except Exception as exc:  # noqa: BLE001
        out.append({"file": "whitespace.docx", "kind": "skipped", "error": str(exc)[:100]})

    # 5) очень длинный нерелевантный документ (шум для BM25: частые «жирные» слова)
    filler = ("Lorem ipsum dolor sit amet consectetur adipiscing elit " * 400)
    try:
        from docx import Document

        doc = Document()
        for i in range(4):
            doc.add_paragraph(f"Служебная записка #{i}. {filler}")
        p = dir_path / "long_irrelevant.docx"
        doc.save(str(p))
        out.append({"file": "long_irrelevant.docx", "kind": "long_irrelevant"})
    except Exception as exc:  # noqa: BLE001
        out.append({"file": "long_irrelevant.docx", "kind": "skipped", "error": str(exc)[:100]})

    return out


def try_ingest(path: Path) -> dict:
    """Прогоняет файл через тот же путь приёмки, что POST /api/documents."""
    import mimetypes

    from app.core.ingestion import ingest_document
    from app.db.models import Document
    from app.db.session import SessionLocal
    from app.config import get_settings

    settings = get_settings()
    db = SessionLocal()
    try:
        doc = Document(
            filename=path.name,
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            category="Robustness",
            status="processing",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        dest = settings.upload_dir / f"{doc.id}{path.suffix.lower()}"
        dest.write_bytes(path.read_bytes())
        ingest_document(db, doc, dest)
        return {"file": path.name, "accepted": True,
                "chunks": doc.chunk_count if hasattr(doc, "chunk_count") else None,
                "status": doc.status}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"file": path.name, "accepted": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
    finally:
        db.close()


def main() -> None:
    import shutil
    import time

    from app.config import get_settings
    from app.core import vectorstore

    settings = get_settings()
    shutil.rmtree(EVAL_DIR, ignore_errors=True)
    settings.ensure_dirs()

    from benchmarks.retrieval_eval import build_index, force_strategy_env

    force_strategy_env("hybrid")
    from app.config import get_settings as gs

    gs().search_hybrid = True
    print("Строю чистый индекс демо-пака…")
    build_index()
    clean_count = vectorstore._collection().count()
    print(f"Чистый индекс: {clean_count} чанков")

    # --- загрязнение ---
    pollution_dir = BASE / "data" / "eval_pollutants"
    pollutants = make_pollutants(pollution_dir)
    ingestion: list[dict] = []
    for p_desc in pollutants:
        path = pollution_dir / p_desc["file"]
        if not path.exists():
            continue
        res = try_ingest(path)
        ingestion.append({**p_desc, **res})
        print(f"  {p_desc['file']}: accepted={res['accepted']} "
              f"{('error=' + res.get('error', '')) if not res['accepted'] else ''}")

    dirty_count = vectorstore._collection().count()
    added = dirty_count - clean_count

    # --- golden set на загрязнённом индексе ---
    golden = json.loads((BASE / "eval" / "golden_retrieval.json").read_text(encoding="utf-8"))
    from app.core import vectorstore as vs

    rows: list[dict] = []
    latencies: list[float] = []
    for item in golden["queries"]:
        t0 = time.perf_counter()
        hits = vs.query(text=item["q"], top_k=5)
        latencies.append((time.perf_counter() - t0) * 1000)
        docs = [h["filename"] for h in hits]
        rank = next((i + 1 for i, n in enumerate(docs) if n == item["doc"]), None)
        rows.append({"id": item["id"], "category": item["category"],
                     "query": item["q"], "target_doc": item["doc"], "rank": rank})

    ranks = [r["rank"] for r in rows]
    from benchmarks.metrics import latency_summary

    dirty_metrics = {
        "recall@1": round(recall_at_k(ranks, 1), 4),
        "recall@3": round(recall_at_k(ranks, 3), 4),
        "recall@5": round(recall_at_k(ranks, 5), 4),
        "mrr@5": round(mrr_at_k(ranks, 5), 4),
        "ndcg@5": round(ndcg_at_k(ranks, 5), 4),
    }
    lat = latency_summary(latencies)
    print(f"\nЗагрязнённый корпус: {dirty_count} чанков (+{added})")
    print(f"Recall@1={dirty_metrics['recall@1']:.1%} R@3={dirty_metrics['recall@3']:.1%} "
          f"MRR@5={dirty_metrics['mrr@5']:.3f} nDCG@5={dirty_metrics['ndcg@5']:.3f} | "
          f"p50={lat.get('p50_ms')}ms")

    # --- сопоставление с чистым baseline (последний retrieval_all прогон) ---
    import glob

    clean_runs = sorted(glob.glob(str(BASE.parent / "results" / "*_retrieval_all*.json")))
    comparison = None
    if clean_runs:
        clean = json.loads(Path(clean_runs[-1]).read_text(encoding="utf-8"))
        hybrid = next((r for r in clean.get("results", []) if r.get("strategy") == "hybrid"), None)
        if hybrid:
            common = [k for k in dirty_metrics if k in hybrid["metrics"]]
            comparison = {k: {"clean": hybrid["metrics"][k], "dirty": dirty_metrics[k],
                              "delta": round(dirty_metrics[k] - hybrid["metrics"][k], 4)}
                          for k in common}
            if len(common) < len(dirty_metrics):
                comparison["_note"] = "часть метрик отсутствует в baseline-артефакте (старая схема)"
            print("\nСравнение с чистым прогоном (hybrid):")
            for k, v in comparison.items():
                print(f"  {k}: {v['clean']} → {v['dirty']} (Δ {v['delta']:+.4f})")

    if "--no-json" not in sys.argv:
        payload = {
            "benchmark": "robustness_eval",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "clean_chunks": clean_count,
            "dirty_chunks": dirty_count,
            "chunks_added_by_pollution": added,
            "pollutants": ingestion,
            "dirty_metrics": dirty_metrics,
            "latency": lat,
            "vs_clean_baseline": comparison,
            "baseline_run": Path(clean_runs[-1]).name if clean_runs else None,
            "rows": rows,
        }
        paths = save_results(payload, "robustness_eval")
        print(f"\nСохранено: {paths}")


if __name__ == "__main__":
    main()
