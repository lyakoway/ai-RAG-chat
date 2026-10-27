"""Reproducible retrieval evaluation: dense-only vs BM25-only vs hybrid (RRF).

Строит индекс демо-пака с нуля в изолированном хранилище backend/data/eval
(как scripts/evaluate.py) и прогоняет golden-набор backend/eval/golden_retrieval.json
через три стратегии на одном и том же корпусе:

  dense  — только векторный поиск (fastembed + ChromaDB)
  bm25   — только лексический BM25 (rank-bm25 поверх чанков коллекции)
  hybrid — BM25 + векторный поиск, сплавленные через RRF (продовый путь)

Метрики: Recall@1/3/5, MRR@5, p50/p95 latency, счётчики запросов/ошибок.
Вывод: таблица в stdout + JSON/CSV в results/.

Запуск (из backend/):
    .venv/bin/python benchmarks/retrieval_eval.py --strategy all
    .venv/bin/python benchmarks/retrieval_eval.py --strategy hybrid --json
    .venv/bin/python benchmarks/retrieval_eval.py --strategy dense --top-k 5

Индекс строится с нуля при каждом запуске — числа воспроизводимы.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

RESULTS_DIR = BASE.parent / "results"

# Изолированное хранилище — env ДО импорта app.* (settings кэшируются при
# первом обращении; см. scripts/evaluate.py).
EVAL_DIR = BASE / "data" / "eval"
os.environ["UPLOAD_DIR"] = str(EVAL_DIR / "uploads")
os.environ["CHROMA_DIR"] = str(EVAL_DIR / "chroma")
os.environ["DATABASE_URL"] = f"sqlite:///{EVAL_DIR / 'app.db'}"

STRATEGIES = ("dense", "bm25", "hybrid")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--strategy",
        default="all",
        choices=(*STRATEGIES, "all"),
        help="какие стратегии оценить (по умолчанию все три)",
    )
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--repeats", type=int, default=1, help="повторов на запрос (latency усредняется)")
    p.add_argument("--warmup", type=int, default=1, help="прогревочных запросов перед замером (не входят в метрики)")
    p.add_argument("--limit", type=int, default=0, help="ограничить число вопросов")
    p.add_argument("--no-json", action="store_true", help="не сохранять JSON/CSV в results/")
    p.add_argument("--label", default="", help="метка запуска в имени файла результатов")
    return p.parse_args()


# ------------------------------------------------------------------ index --

def build_index() -> None:
    """Чистое хранилище + индексация демо-файлов (как POST /api/documents/demo)."""
    from app.config import get_settings
    from app.core.ingestion import ingest_document
    from app.db.models import Document
    from app.db.session import SessionLocal, init_db

    settings = get_settings()
    shutil.rmtree(EVAL_DIR, ignore_errors=True)
    settings.ensure_dirs()
    init_db()

    db = SessionLocal()
    try:
        for path in sorted(settings.samples_dir.iterdir()):
            ext = path.suffix.lower()
            if ext not in {".pdf", ".docx", ".xlsx"}:
                continue
            import mimetypes
            import shutil as sh

            doc = Document(
                filename=path.name,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                category="Demo",
                status="processing",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            dest = settings.upload_dir / f"{doc.id}{ext}"
            sh.copyfile(path, dest)
            doc.size_bytes = dest.stat().st_size
            db.add(doc)
            db.commit()
            ingest_document(db, doc, dest)
    finally:
        db.close()


# ------------------------------------------------------------- strategies --

def dense_search(text: str, top_k: int) -> list[dict]:
    """Только векторный ANN-поиск ChromaDB (без BM25-сплава)."""
    from app.core import vectorstore
    from app.core.embeddings import get_embeddings

    emb = get_embeddings()
    count = vectorstore._collection().count()
    if count == 0:
        return []
    qvec = emb.embed_query(text)
    try:
        res = vectorstore._collection().query(
            query_embeddings=[qvec],
            n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
        )
    except RuntimeError:
        res = vectorstore._brute_force_query(qvec, top_k, None)

    out = []
    for chunk_id, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        out.append(
            {
                "id": chunk_id,
                "text": doc,
                "filename": meta.get("filename"),
                "page": meta.get("page"),
                "score": round(1.0 - float(dist), 4),
            }
        )
    return out


def bm25_only_search(text: str, top_k: int) -> list[dict]:
    """Только BM25 по чанкам коллекции; метаданные добираются одним get()."""
    from app.core import bm25 as bm25_mod
    from app.core import vectorstore

    scores = bm25_mod.bm25_search(text=text, top_k=top_k)
    if not scores:
        return []
    ids = list(scores)
    metas = vectorstore._collection().get(ids=ids, include=["metadatas", "documents"])
    by_id = {mid: (m, d) for mid, m, d in zip(metas["ids"], metas["metadatas"], metas["documents"])}
    out = []
    for chunk_id in sorted(scores, key=scores.get, reverse=True):
        meta, doc = by_id.get(chunk_id, ({}, ""))
        out.append(
            {
                "id": chunk_id,
                "text": doc,
                "filename": meta.get("filename"),
                "page": meta.get("page"),
                "score": round(scores[chunk_id], 4),
            }
        )
    return out


def hybrid_search(text: str, top_k: int) -> list[dict]:
    """Продовый путь: vectorstore.query c SEARCH_HYBRID=1 (RRF-сплав)."""
    from app.core import vectorstore

    return vectorstore.query(text=text, top_k=top_k)


SEARCHERS = {"dense": dense_search, "bm25": bm25_only_search, "hybrid": hybrid_search}


def force_strategy_env(strategy: str) -> None:
    """Стратегии включаются env ДО импорта app.*; вызывается из main() до импортов."""
    os.environ["SEARCH_HYBRID"] = "1" if strategy == "hybrid" else "0"
    os.environ.pop("SEARCH_RERANK", None)


# ------------------------------------------------------------------- run --

def run_strategy(name: str, queries: list[dict], top_k: int, repeats: int, warmup: int) -> dict:
    searcher = SEARCHERS[name]

    # Прогрев: первый запрос кодирует моделью/строит BM25-индекс — не метрики.
    for q in queries[:warmup]:
        searcher(q["q"], top_k)

    rows: list[dict] = []
    latencies: list[float] = []
    errors = 0
    for item in queries:
        lat_samples: list[float] = []
        hits: list[dict] = []
        err = None
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            try:
                hits = searcher(item["q"], top_k)
                lat_samples.append((time.perf_counter() - t0) * 1000)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                err = str(exc)
                break
        latencies.extend(lat_samples)
        docs = [h["filename"] for h in hits]
        rank = None
        if docs:
            try:
                from benchmarks.metrics import first_hit_rank

                rank = first_hit_rank(docs, item["doc"])
            except Exception:
                rank = next((i + 1 for i, n in enumerate(docs) if n == item["doc"]), None)
        rows.append(
            {
                "id": item["id"],
                "category": item["category"],
                "query": item["q"],
                "target_doc": item["doc"],
                "rank": rank,
                "top1_doc": docs[0] if docs else None,
                "retrieved_docs": docs,
                "latency_ms": round(lat_samples[-1], 2) if lat_samples else None,
                "error": err,
            }
        )

    from benchmarks.metrics import latency_summary, mrr_at_k, ndcg_at_k, recall_at_k

    ranks = [r["rank"] for r in rows]
    return {
        "strategy": name,
        "n_queries": len(rows),
        "n_errors": errors,
        "metrics": {
            "recall@1": round(recall_at_k(ranks, 1), 4),
            "recall@3": round(recall_at_k(ranks, 3), 4),
            "recall@5": round(recall_at_k(ranks, 5), 4),
            "mrr@5": round(mrr_at_k(ranks, 5), 4),
            "ndcg@5": round(ndcg_at_k(ranks, 5), 4),
        },
        "latency": latency_summary(latencies),
        "rows": rows,
    }


def per_category(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for cat in sorted({r["category"] for r in rows}):
        subset = [r for r in rows if r["category"] == cat]
        ranks = [r["rank"] for r in subset]
        from benchmarks.metrics import mrr_at_k, ndcg_at_k, recall_at_k

        out[cat] = {
            "n": len(subset),
            "recall@1": round(recall_at_k(ranks, 1), 4),
            "recall@3": round(recall_at_k(ranks, 3), 4),
            "mrr@5": round(mrr_at_k(ranks, 5), 4),
            "ndcg@5": round(ndcg_at_k(ranks, 5), 4),
        }
    return out


def print_report(results: list[dict]) -> None:
    print(f"\n{'Strategy':<10} {'R@1':>7} {'R@3':>7} {'R@5':>7} {'MRR@5':>7} {'nDCG@5':>7} "
          f"{'p50 ms':>8} {'p95 ms':>8} {'errs':>5}")
    print("-" * 78)
    for r in results:
        m, lat = r["metrics"], r["latency"]
        print(
            f"{r['strategy']:<10} {m['recall@1']:>7.1%} {m['recall@3']:>7.1%} "
            f"{m['recall@5']:>7.1%} {m['mrr@5']:>7.3f} {m.get('ndcg@5', 0):>7.3f} "
            f"{lat.get('p50_ms', 0):>8.1f} {lat.get('p95_ms', 0):>8.1f} {r['n_errors']:>5}"
        )
    print()
    for r in results:
        print(f"[{r['strategy']}] per-category:")
        for cat, c in per_category(r["rows"]).items():
            print(f"  {cat:<14} n={c['n']:<3} R@1={c['recall@1']:.1%}  R@3={c['recall@3']:.1%}")
    # Промахи hybrid-конфигурации (продовой) — для ручного разбора.
    hybrid = next((r for r in results if r["strategy"] == "hybrid"), None)
    if hybrid:
        misses = [x for x in hybrid["rows"] if x["rank"] is None or x["rank"] > 1]
        if misses:
            print(f"\n[{hybrid['strategy']}] не top-1 ({len(misses)}):")
            for m in misses:
                print(f"  rank {m['rank'] or '—'}: {m['query'][:70]} → {m['top1_doc']}")


def main() -> None:
    args = parse_args()
    strategies = list(STRATEGIES) if args.strategy == "all" else [args.strategy]
    # env для первой стратегии должен быть выставлен до импорта app.*
    force_strategy_env(strategies[0])

    from app.core.embeddings import active_model_name

    golden = json.loads((BASE / "eval" / "golden_retrieval.json").read_text(encoding="utf-8"))
    queries = golden["queries"][: args.limit] if args.limit else golden["queries"]

    print(f"Golden set: {golden['name']} | queries={len(queries)} | top_k={args.top_k} | repeats={args.repeats}")
    print("Индексация демо-пака с нуля…")
    build_index()

    all_results: list[dict] = []
    for s in strategies:
        force_strategy_env(s)
        # settings кэшируются; для смены SEARCH_HYBRID обновляем поле напрямую.
        from app.config import get_settings

        get_settings().search_hybrid = s == "hybrid"
        print(f"\n=== {s} ===")
        all_results.append(run_strategy(s, queries, args.top_k, args.repeats, args.warmup))

    print_report(all_results)

    if not args.no_json:
        from benchmarks.metrics import command_line, git_commit, iso_utc, save_results

        payload = {
            "benchmark": "retrieval_eval",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "golden_set": golden["name"],
            "golden_set_version": golden.get("provenance"),
            "corpus": "backend/samples (6 files)",
            "embedding_model": active_model_name(),
            "chunking": {"chunk_size": 800, "chunk_overlap": 120, "tokenizer": "cl100k_base"},
            "top_k": args.top_k,
            "repeats": args.repeats,
            "warmup_queries": args.warmup,
            "hardware": "Apple M1 Pro, 16 GB (если не указано иное в docs/benchmark.md)",
            "results": [{k: v for k, v in r.items() if k != "rows"} for r in all_results],
            "per_category": {r["strategy"]: per_category(r["rows"]) for r in all_results},
            "rows": [
                {**row, "strategy": r["strategy"]}
                for r in all_results
                for row in r["rows"]
            ],
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"retrieval_{args.strategy}{label}")
        print(f"\nСохранено: {paths}")


if __name__ == "__main__":
    main()
