"""Reranker benchmark: cross-encoder rerank поверх hybrid retrieval.

Воспроизводит ранний замер «Reranker: Recall@1 41.7% vs hybrid 87.2%»
(README Measurements; оригинальный артефакт не сохранился — Stage 5 fix).
Модель: BAAI/bge-reranker-base (fastembed TextCrossEncoder, ~1 GB ONNX,
скачивается при первом запуске). Кандидаты: top-20 hybrid (BM25+RRF),
rerank, метрики по top-k.

Метрики: Recall@1/3, Recall@5, MRR@5, nDCG@5, rerank latency p50/p95.
Артефакт: results/<ts>_reranker.json (и benchmark-схема для сравнения).

Запуск:
    WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/reranker_eval.py \
        [--candidates 20] [--top-k 5] [--limit 0]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.metrics import (  # noqa: E402
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)

DATASET = Path(__file__).resolve().parent.parent / "eval" / "golden_retrieval.json"


def first_rank(fnames: list[str], target: str) -> int | None:
    return next((i for i, fn in enumerate(fnames, 1) if fn == target), None)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Cross-encoder reranker benchmark")
    p.add_argument("--candidates", type=int, default=20, help="размер пула кандидатов hybrid")
    p.add_argument("--top-k", type=int, default=5, help="сколько оставить после rerank")
    p.add_argument("--limit", type=int, default=0, help="ограничить число запросов")
    p.add_argument("--out", default=None, help="имя артефакта (по умолчанию reranker)")
    args = p.parse_args()

    golden = json.loads(DATASET.read_text(encoding="utf-8"))
    queries = golden["queries"][: args.limit] if args.limit else golden["queries"]

    from app.core.rag import retrieve as rag_retrieve
    from app.core.rerank import rerank as do_rerank

    rows: list[dict] = []
    rerank_latencies: list[float] = []
    for item in queries:
        target = item["doc"]
        q = item["q"]

        # 1) Hybrid candidates (top-N pool, тот же путь что и prod)
        t0 = time.perf_counter()
        candidates = rag_retrieve(
            query=q, workspace_id="default", top_k=args.candidates
        )
        t_retrieve = round((time.perf_counter() - t0) * 1000, 1)

        # 2) Cross-encoder rerank
        t0 = time.perf_counter()
        reranked = do_rerank(q, candidates, text_key="text")
        t_rerank = round((time.perf_counter() - t0) * 1000, 1)
        rerank_latencies.append(t_rerank)

        hits = reranked[: args.top_k]
        fnames = [h["filename"] for h in hits]
        rank = first_rank(fnames, target)
        rows.append({
            "id": item["id"], "category": item["category"], "query": q,
            "target_doc": target, "rank": rank,
            "retrieved": fnames,
            "retrieval_ms": t_retrieve, "rerank_ms": t_rerank,
        })

    def _ranks() -> list[int | None]:
        return [r["rank"] for r in rows]

    ranks = _ranks()
    summary = {
        "model": "BAAI/bge-reranker-base (fastembed TextCrossEncoder, ONNX ~1 GB)",
        "candidates_pool": args.candidates,
        "top_k": args.top_k,
        "n_queries": len(rows),
        "recall@1": round(recall_at_k(ranks, 1), 4),
        "recall@3": round(recall_at_k(ranks, 3), 4),
        "recall@5": round(recall_at_k(ranks, 5), 4),
        "mrr@5": round(mrr_at_k(ranks, 5), 4),
        "ndcg@5": round(ndcg_at_k(ranks, 5), 4),
        "rerank_latency_ms": {
            "p50": round(statistics.median(rerank_latencies), 1),
            "p95": round(max(rerank_latencies), 1) if len(rerank_latencies) < 20
                   else sorted(rerank_latencies)[int(len(rerank_latencies) * 0.95)],
            "mean": round(statistics.fmean(rerank_latencies), 1),
        },
    }

    print(json.dumps(summary, ensure_ascii=False, indent=1))

    # Сравнение с hybrid baseline из последнего retrieval-артефакта
    baseline_file = sorted(Path("../results").glob("*retrieval_hybrid.json"))
    if baseline_file:
        base = json.loads(baseline_file[-1].read_text(encoding="utf-8"))
        for r in base.get("results", [base]):
            if isinstance(r, dict) and r.get("strategy") == "hybrid":
                summary["hybrid_baseline"] = r["metrics"]
                break

    from benchmarks.metrics import save_results

    save_results(
        {"benchmark": "reranker_eval", "summary": summary, "rows": rows,
         "dataset": "golden_retrieval.json (47 queries)"},
        args.out or "reranker",
    )
    print(f"Артефакт: results/*{args.out or 'reranker'}.json")


if __name__ == "__main__":
    main()
