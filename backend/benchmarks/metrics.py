"""Shared benchmark utilities: latency metrics, ranking metrics, token estimation.

Все функции — чистые (без side effects и без импортов app.*), чтобы их можно
покрыть юнит-тестами и переиспользовать во всех benchmark-скриптах.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
EVAL_DIR = BASE / "eval"
RESULTS_DIR = BASE.parent / "results"


# ---------------------------------------------------------------- latencies --

def percentile(values: list[float], p: float) -> float:
    """Percentile with linear interpolation (numpy-style), 0 <= p <= 100.

    Пустой список → 0.0 (вызывающий код обязан проверять выборку сам).
    """
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    rank = (len(s) - 1) * (p / 100.0)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (rank - lo))


def latency_summary(values_ms: list[float]) -> dict:
    """p50/p95/p99 + mean/stdev/min/max по выборке задержек в мс."""
    if not values_ms:
        return {"n": 0}
    return {
        "n": len(values_ms),
        "mean_ms": round(statistics.fmean(values_ms), 2),
        "stdev_ms": round(statistics.stdev(values_ms), 2) if len(values_ms) > 1 else 0.0,
        "min_ms": round(min(values_ms), 2),
        "p50_ms": round(percentile(values_ms, 50), 2),
        "p95_ms": round(percentile(values_ms, 95), 2),
        "p99_ms": round(percentile(values_ms, 99), 2),
        "max_ms": round(max(values_ms), 2),
    }


# ----------------------------------------------------------- rank metrics --

def recall_at_k(ranks: list[int | None], k: int) -> float:
    """Доля запросов, где релевантный документ найден в топ-k (rank is not None and rank <= k)."""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mrr_at_k(ranks: list[int | None], k: int) -> float:
    """Mean Reciprocal Rank: mean(1/rank) по найденным, 0 для ненайденных."""
    if not ranks:
        return 0.0
    return sum(1.0 / r for r in ranks if r is not None and r <= k) / len(ranks)


def ndcg_at_k(ranks: list[int | None], k: int) -> float:
    """nDCG@K для набора с одним релевантным документом на запрос.

    DCG@K = Σ rel_i / log2(i+1); с одним релевантным на ранге r: DCG = 1/log2(r+1).
    IDCG@K = 1/log2(1+1) = 1 (идеальный ранг 1), поэтому nDCG = mean(1/log2(r+1)),
    0 для ненайденных. При одном релевантном nDCG@K жёстче наказывает низкие
    ранги, чем MRR@K (rank 3: MRR 0.333, nDCG 0.5; rank 5: MRR 0.2, nDCG 0.387).
    """
    if not ranks:
        return 0.0
    import math

    return sum(1.0 / math.log2(r + 1) for r in ranks if r is not None and r <= k) / len(ranks)


def first_hit_rank(retrieved_docs: list[str], target: str) -> int | None:
    """Ранг (1-based) первого появления target в списке имён документов, None если нет."""
    for i, name in enumerate(retrieved_docs, start=1):
        if name == target:
            return i
    return None


# ------------------------------------------------------------ token count --

_ENCODER = None


def count_tokens(text: str) -> int:
    """tiktoken cl100k_base — та же кодировка, что использует chunking проекта.

    Оценка клиентская: у облачных провайдеров фактический токенизатор может
    отличаться; такие значения помечаются как estimate в результатах.
    """
    global _ENCODER
    if _ENCODER is None:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODER.encode(text))


# ------------------------------------------------------------------- io --

def now_ms() -> float:
    return time.perf_counter() * 1000.0


def iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_commit() -> str | None:
    import subprocess

    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(BASE.parent),
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            or None
        )
    except Exception:
        return None


def command_line() -> str:
    """Точная команда запуска текущего процесса — попадает в артефакт для воспроизведения."""
    import shlex

    return " ".join(shlex.quote(a) for a in sys.argv)


def golden_set_hash() -> dict[str, str]:
    """sha256 (первые 16 hex) каждого golden-набора в eval/ — версия данных в артефакте."""
    import hashlib

    out: dict[str, str] = {}
    for p in sorted(EVAL_DIR.glob("*.json")):
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def dependency_versions() -> dict[str, str]:
    """Версии Python/платформы и ключевых зависимостей benchmark-контура."""
    import platform
    from importlib.metadata import PackageNotFoundError, version

    out = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("fastembed", "chromadb", "rank-bm25", "tiktoken", "openai",
                 "anthropic", "httpx", "pydantic", "fastapi", "psutil"):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            continue
    return out


def save_results(payload: dict, name: str, fmt: list[str] | None = None,
                 out_dir: Path | None = None) -> dict:
    """Сохраняет результаты в results/<timestamp>_<name>.json (+ .csv для rows).

    payload["rows"] — список плоских словарей: попадут в CSV (по одному ряду
    на запрос/итерацию). Автоматически добавляет env-блок (sha256 golden set,
    версии зависимостей), если его нет. Возвращает словарь {формат: путь}.
    """
    results_dir = out_dir or RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    paths: dict[str, str] = {}
    fmt = fmt or ["json", "csv"]

    payload.setdefault("env", {
        "golden_set_sha256": golden_set_hash(),
        "dependencies": dependency_versions(),
    })

    if "json" in fmt:
        p = results_dir / f"{stamp}_{name}.json"
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        paths["json"] = str(p)

    rows = payload.get("rows")
    if rows and "csv" in fmt:
        keys: list[str] = []
        for r in rows:
            for k in r:
                if k not in keys and not isinstance(r[k], (dict, list)):
                    keys.append(k)
        p = results_dir / f"{stamp}_{name}.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        paths["csv"] = str(p)
    return paths


def load_golden(filename: str) -> dict:
    p = EVAL_DIR / filename
    return json.loads(p.read_text(encoding="utf-8"))


def env_or_default(flag: str, default: str) -> str:
    return flag if len(sys.argv) > 1 else default
