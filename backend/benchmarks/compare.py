"""Сравнение двух прогонов benchmark (baseline vs candidate) с флагами регрессий.

Работает с JSON-артефактами results/ любых benchmark-скриптов проекта:
рекурсивно собирает числовые листья обоих файлов, сопоставляет по пути в JSON
и размечает каждое совпадение:

  QUALITY   (recall@k, mrr@5, ndcg@5, correctness_rate, citation_*, refusal_*,
             judge_*, success_rate, n_ok)  — ниже = хуже;
  LATENCY   (*_ms p50/p95/p99, tpot, prefill, ttfc, e2e) — выше = хуже;
  COST      (cost_usd*) — выше = хуже;
  остальные числовые поля — INFO (без вердикта).

Статусы: OK / IMPROVED / REGRESSION / INFO. Регрессия качества — хуже baseline
более чем на --quality-eps (по умолчанию 0.005, допуски на шум округления);
регрессия latency — хуже baseline более чем на --latency-tolerance (доля, по
умолчанию 25%). Код выхода 1 при наличии REGRESSION — пригоден для CI-гейта.

Запуск:
    .venv/bin/python benchmarks/compare.py \
        --baseline ../results/20261022_231310_retrieval_all_latency_clean.json \
        --candidate  ../results/<новый>_retrieval_all.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Суффиксы путей (без учёта родительских сегментов) и направление «хорошего».
QUALITY_SUFFIXES = (
    "recall@1", "recall@3", "recall@5", "mrr@5", "ndcg@5",
    "correctness_rate", "citation_validity_rate", "citation_precision_mean",
    "citation_recall_rate", "citation_target_top1_rate",
    "refusal_no_hallucination_rate", "refusal_strict_no_citations_rate",
    "judge_faithfulness_avg", "judge_relevance_avg", "judge_citations_avg",
    "judge_vs_citations_agreement", "completeness_coverage_mean",
    "success_rate", "n_ok",
)
LATENCY_SUFFIXES = ("p50_ms", "p95_ms", "p99_ms")
COST_SUFFIXES = ("cost_usd_mean",)
SKIP_PATH_PARTS = ("rows", "env", "golden_set_sha256", "dependencies", "errors",
                   "finish_reasons", "questions", "retrieved_docs", "system_monitor")


def flatten_numbers(obj, prefix: str = "") -> dict[str, float]:
    """Числовые листья словаря → {путь: значение}.

    Списки словарей разворачиваются с индексом (results.0.metrics.recall@1) —
    между прогонами одного скрипта порядок элементов стабилен. Списки-«ряды»
    (rows) и служебные секции пропускаются по имени ключа.
    """
    out: dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(part in k for part in SKIP_PATH_PARTS):
                continue
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_numbers(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten_numbers(v, f"{prefix}.{i}"))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)) and prefix:
        out[prefix] = float(obj)
    return out


def classify(path: str) -> str:
    """Категория метрики по суффиксу пути."""
    leaf = path.split(".")[-1].lower()
    if leaf in QUALITY_SUFFIXES:
        return "QUALITY"
    if leaf in LATENCY_SUFFIXES or leaf.endswith("_ms"):
        return "LATENCY"
    if leaf in COST_SUFFIXES or "cost_usd" in leaf:
        return "COST"
    return "INFO"


def verdict(category: str, base: float, cand: float,
            quality_eps: float, latency_tolerance: float) -> str:
    """OK / IMPROVED / REGRESSION / INFO для одной пары значений.

    LATENCY/COST: регрессия — рост свыше tolerance (доля); улучшение — падение
    свыше quality_eps. QUALITY: регрессия — падение свыше quality_eps.
    Всё в пределах допусков — OK (межпрогонный шум latency до 60% наблюдён,
    поэтому по умолчанию tolerance 0.25 и смысл имеет только устойчивый рост).
    """
    if category == "INFO":
        return "INFO"
    delta = cand - base
    if category == "LATENCY":
        worse = base > 0 and cand > base * (1 + latency_tolerance)
        better = delta < -quality_eps
    elif category == "COST":
        # относительный допуск: абсолютный eps=0.005 бессмыслен для $0.0002
        worse = base > 0 and cand > base * (1 + latency_tolerance)
        better = base > 0 and cand < base * (1 - quality_eps)
    else:  # QUALITY
        worse = cand < base - quality_eps
        better = delta > quality_eps
    if worse:
        return "REGRESSION"
    return "IMPROVED" if better else "OK"


def compare_payloads(baseline: dict, candidate: dict,
                     quality_eps: float = 0.005,
                     latency_tolerance: float = 0.25) -> list[dict]:
    """Сопоставляет числовые листья двух артефактов. Возвращает ряды таблицы."""
    b = flatten_numbers(baseline)
    c = flatten_numbers(candidate)
    rows = []
    for path in sorted(set(b) & set(c)):
        base, cand = b[path], c[path]
        if base == 0 and cand == 0:
            continue
        cat = classify(path)
        rows.append({
            "metric": path,
            "category": cat,
            "baseline": round(base, 5),
            "candidate": round(cand, 5),
            "delta": round(cand - base, 5),
            "verdict": verdict(cat, base, cand, quality_eps, latency_tolerance),
        })
    return rows


def print_table(rows: list[dict]) -> None:
    print(f"{'metric':<58} {'cat':<8} {'baseline':>12} {'candidate':>12} "
          f"{'delta':>10} {'verdict':<10}")
    print("-" * 116)
    for r in rows:
        print(f"{r['metric']:<58} {r['category']:<8} {r['baseline']:>12} "
              f"{r['candidate']:>12} {r['delta']:>10} {r['verdict']:<10}")
    n_reg = sum(1 for r in rows if r["verdict"] == "REGRESSION")
    n_imp = sum(1 for r in rows if r["verdict"] == "IMPROVED")
    print(f"\nИтого: {len(rows)} сопоставлено | REGRESSION={n_reg} | IMPROVED={n_imp}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--baseline", required=True, help="JSON baseline-прогона")
    p.add_argument("--candidate", required=True, help="JSON candidate-прогона")
    p.add_argument("--quality-eps", type=float, default=0.005)
    p.add_argument("--latency-tolerance", type=float, default=0.25,
                   help="допустимый рост latency, доля (0.25 = +25%)")
    p.add_argument("--fail-on-regression", action="store_true",
                   help="код выхода 1 при наличии REGRESSION (для CI)")
    args = p.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    rows = compare_payloads(baseline, candidate, args.quality_eps, args.latency_tolerance)
    print(f"baseline: {args.baseline}\ncandidate: {args.candidate}\n")
    print_table(rows)
    if args.fail_on_regression and any(r["verdict"] == "REGRESSION" for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
