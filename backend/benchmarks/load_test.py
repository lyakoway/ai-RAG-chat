"""Load test: concurrency levels against the live FastAPI backend.

Долбит реальный SSE-эндпоинт /api/chat на запущенном uvicorn (по умолчанию
http://localhost:8000) уровнями конкурентности 1/2/5/10: короткий и длинный
контекст, warm-up, повторы. Метрики: success rate, запросов/сек, p50/p95/p99
end-to-end latency, output tokens/sec (из usage API, где доступен), ошибки и
таймауты. Результаты: results/<ts>_load_test.json + .csv.

Безопасность: общий лимит запросов на уровень (--requests), таймаут на запрос,
no retry-storm (одна попытка, ошибка фиксируется). Нагрузка в N параллельных
SSE-потоков к СВОЕМУ локальному серверу; облачный провайдер получает ровно
N одновременных запросов — как реальный пользователь с N вкладками.

Запуск:
    # 1. поднять сервер: uvicorn app.main:app --port 8000 (ZAI_API_KEY в backend/.env)
    # 2. из backend/:
    .venv/bin/python benchmarks/load_test.py --levels 1 2 5 10 --requests 8 --model zai:glm-5.3-flash
    .venv/bin/python benchmarks/load_test.py --levels 1 5 --requests 6 --model mock --url http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

from benchmarks.metrics import (  # noqa: E402
    command_line,
    count_tokens,
    git_commit,
    iso_utc,
    latency_summary,
    percentile,
    save_results,
)

# Классы запросов: короткий и длинный (контекст и ожидаемый ответ).
QUESTION_CLASSES = {
    "short": "Сколько дней отпуска положено сотруднику?",
    "long_ctx": "Подробно опиши условия удалённой работы: дни, часы онлайн, оборудование, компенсации и отпуск.",
    "long_answer": "Составь подробную памятку для нового сотрудника: удалёнка, тарифы, скидки и безопасность по документам.",
}

_CITATION_RE = re.compile(r"\[\d{1,2}\]")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", default="http://localhost:8000", help="базовый URL backend")
    p.add_argument("--levels", type=int, nargs="+", default=[1, 2, 5, 10], help="уровни конкурентности (fixed concurrency)")
    p.add_argument("--requests", type=int, default=8, help="всего запросов на каждый уровень")
    p.add_argument("--rate", type=float, default=None,
                   help="если задано: fixed request rate (запросов/сек) вместо фиксированной конкурентности")
    p.add_argument("--classes", nargs="+", default=["short", "long_ctx"],
                   choices=list(QUESTION_CLASSES), help="классы запросов для микса")
    p.add_argument("--model", default="mock", help="модель (zai:glm-5.3-flash / mock / ollama:…)")
    p.add_argument("--timeout", type=float, default=120.0, help="таймаут одного запроса, с")
    p.add_argument("--warmup", type=int, default=2, help="warm-up запросов перед уровнями")
    p.add_argument("--check-citations", action="store_true",
                   help="детерминированная проверка: в ответе есть [n]-ссылка (качество под нагрузкой)")
    p.add_argument("--monitor", action="store_true", help="снимать CPU/RAM/swap системы во время уровня")
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    return p.parse_args()


async def one_chat_request(client, base_url: str, question: str, model: str, timeout: float) -> dict:
    """Один SSE-запрос к /api/chat; собирает тайминги и токены из потока."""
    import httpx

    payload = {"message": question, "model": model, "mode": "rag", "lang": "ru"}
    r = {"ok": False, "error": None, "sources": 0, "answer_chars": 0, "usage": None,
         "answer_text": ""}
    t0 = time.perf_counter()
    first_event_ts = None
    first_token_ts = None
    last_token_ts = None
    tokens_seen = 0
    try:
        timeout_conf = httpx.Timeout(connect=10.0, read=timeout, write=30.0, pool=10.0)
        async with client.stream("POST", f"{base_url}/api/chat", json=payload, timeout=timeout_conf) as resp:
            r["http_status"] = resp.status_code
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")
            event = None
            async for raw in resp.aiter_lines():
                if not raw:
                    event = None
                    continue
                if raw.startswith("event:"):
                    event = raw[6:].strip()
                    if first_event_ts is None:
                        first_event_ts = time.perf_counter()
                    continue
                if raw.startswith("data:"):
                    try:
                        data = json.loads(raw[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event == "sources":
                        r["sources"] = len(data.get("sources") or [])
                    elif event == "token":
                        if first_token_ts is None:
                            first_token_ts = time.perf_counter()
                        last_token_ts = time.perf_counter()
                        tokens_seen += 1
                        delta = data.get("delta") or ""
                        r["answer_chars"] += len(delta)
                        if len(r["answer_text"]) < 4000:
                            r["answer_text"] += delta
                    elif event == "error":
                        raise RuntimeError(f"SSE error: {str(data)[:200]}")
                    elif event == "done":
                        r["ok"] = True
                        break
        # usage недоступен через SSE чата — токены оцениваем по символам ниже.
    except Exception as exc:  # noqa: BLE001
        r["error"] = f"{type(exc).__name__}: {exc}"[:250]

    now = time.perf_counter()
    r["total_ms"] = round((now - t0) * 1000, 1)
    r["first_event_ms"] = round((first_event_ts - t0) * 1000, 1) if first_event_ts else None
    r["first_token_ms"] = round((first_token_ts - t0) * 1000, 1) if first_token_ts else None
    stream_ms = (last_token_ts - first_token_ts) * 1000 if first_token_ts and last_token_ts else 0.0
    # Оценка: ~4 символа на токен для RU/EN смеси — консервативная клиентская оценка.
    est_tokens = max(1, r["answer_chars"] // 4)
    r["out_tokens_est"] = est_tokens
    r["tokens_per_sec_est"] = round(est_tokens / (stream_ms / 1000), 1) if stream_ms > 0 and r["ok"] else None
    # Детерминированная проверка формата под нагрузкой: ответ ссылается на источники.
    r["has_citation"] = bool(_CITATION_RE.search(r["answer_text"])) if r["ok"] else None
    del r["answer_text"]  # сырой текст в CSV не нужен, экономим размер артефакта
    return r


def swap_used_mb() -> float | None:
    import re as _re
    import subprocess

    try:
        out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True,
                             timeout=5, check=True).stdout
        m = _re.search(r"used = ([\d.]+)M", out)
        return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


async def run_level(level: int, n_requests: int, args, questions: list[dict]) -> tuple[dict, list[dict]]:
    """Один уровень нагрузки.

    fixed concurrency (по умолчанию): n_requests воркеров, не более `level`
    одновременно (Semaphore). fixed rate (--rate R): запросы стартуют каждые
    1/R секунд, конкурентность возникает естественно из латентности ответов.
    """
    import httpx

    questions = [{"text": QUESTION_CLASSES[c], "cls": c} for c in questions]

    async def worker(item: tuple[int, dict]) -> dict:
        i, q = item
        async with httpx.AsyncClient() as client:
            r = await one_chat_request(client, args.url, q["text"], args.model, args.timeout)
            r["question_class"] = q["cls"]
            return r

    monitor_task = None
    if args.monitor:
        monitor_task = asyncio.create_task(_monitor_system(0.5))

    t0 = time.perf_counter()
    rows: list[dict] = []
    if args.rate:
        interval = 1.0 / args.rate
        tasks = []
        for i in range(n_requests):
            tasks.append(asyncio.create_task(worker((i, questions[i % len(questions)]))))
            if i < n_requests - 1:
                await asyncio.sleep(interval)
        rows = await asyncio.gather(*tasks)
    else:
        sem = asyncio.Semaphore(level)

        async def bounded(item):
            async with sem:
                return await worker(item)

        rows = await asyncio.gather(*[bounded((i, questions[i % len(questions)]))
                                      for i in range(n_requests)])
    wall = time.perf_counter() - t0

    if monitor_task:
        monitor_task.cancel()
        sys_samples = [s for s in (await _drain(monitor_task)) or []]
    else:
        sys_samples = []

    ok = [r for r in rows if r["ok"]]
    totals = [r["total_ms"] for r in ok]
    tps = [r["tokens_per_sec_est"] for r in ok if r["tokens_per_sec_est"]]
    agg = {
        "mode": f"fixed_rate_{args.rate}/s" if args.rate else f"fixed_concurrency_{level}",
        "concurrency": level,
        "rate_rps": args.rate,
        "n_requests": n_requests,
        "n_ok": len(ok),
        "success_rate": round(len(ok) / n_requests, 4),
        "wall_s": round(wall, 2),
        "requests_per_sec": round(n_requests / wall, 3),
        "e2e": latency_summary(totals),
        "first_token": latency_summary([r["first_token_ms"] for r in ok if r["first_token_ms"]]),
        "tokens_per_sec_est_p50": round(percentile(tps, 50), 1) if tps else None,
        "errors": [r["error"] for r in rows if not r["ok"]][:5],
        "citations_present_rate": (
            round(sum(1 for r in ok if r.get("has_citation")) / len(ok), 4)
            if args.check_citations and ok else None
        ),
        "system_monitor": _monitor_summary(sys_samples),
    }
    return agg, rows


async def _monitor_system(interval_s: float):
    """Фоновый сборщик системных метрик во время уровня нагрузки."""
    import psutil

    samples = []
    try:
        while True:
            samples.append({
                "ts": time.perf_counter(),
                "cpu_percent": psutil.cpu_percent(interval=None),
                "ram_used_percent": psutil.virtual_memory().percent,
                "swap_used_mb": swap_used_mb(),
            })
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        return samples


async def _drain(task):
    try:
        return await task
    except asyncio.CancelledError:
        return task.result() if task.done() and not task.cancelled() else []


def _monitor_summary(samples: list[dict]) -> dict | None:
    if not samples:
        return None
    cpu = [s["cpu_percent"] for s in samples]
    ram = [s["ram_used_percent"] for s in samples]
    swaps = [s["swap_used_mb"] for s in samples if s["swap_used_mb"] is not None]
    return {
        "n_samples": len(samples),
        "cpu_percent_mean": round(sum(cpu) / len(cpu), 1),
        "cpu_percent_max": round(max(cpu), 1),
        "ram_used_percent_max": round(max(ram), 1),
        "swap_used_mb_max": round(max(swaps), 0) if swaps else None,
    }


async def main_async(args) -> None:
    import re as _re

    import httpx

    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{args.url}/api/models", timeout=10.0)
            print(f"Сервер {args.url}: HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            print(f"Сервер {args.url} недоступен: {exc}")
            print("Подними backend: cd backend && .venv/bin/uvicorn app.main:app --port 8000")
            sys.exit(2)

    classes = args.classes
    if args.warmup:
        print(f"Warm-up: {args.warmup} запросов…")
        async with httpx.AsyncClient() as client:
            for i in range(args.warmup):
                await one_chat_request(client, args.url, QUESTION_CLASSES[classes[i % len(classes)]],
                                       args.model, args.timeout)

    levels: list[dict] = []
    all_rows: list[dict] = []
    for level in args.levels:
        mode = f"rate={args.rate}/s" if args.rate else f"concurrency={level}"
        print(f"=== {mode}: {args.requests} запросов, классы={classes} ===")
        agg, rows = await run_level(level, args.requests, args, classes)
        for row in rows:
            row["concurrency"] = level
            row["has_citation"] = bool(_re.search(r"\[\d{1,2}\]", "")) if False else None
        all_rows.extend(rows)
        levels.append(agg)
        cite = f" cite={agg['citations_present_rate']:.0%}" if agg["citations_present_rate"] is not None else ""
        mon = f" cpu={agg['system_monitor']['cpu_percent_mean']}%" if agg["system_monitor"] else ""
        print(f"  ok={agg['n_ok']}/{agg['n_requests']} | rps={agg['requests_per_sec']} | "
              f"p50={agg['e2e'].get('p50_ms')}ms p95={agg['e2e'].get('p95_ms')}ms | "
              f"tok/s={agg['tokens_per_sec_est_p50']}{cite}{mon}")

    print(f"\n{'conc':>5} {'ok%':>6} {'rps':>6} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'tok/s':>7}")
    for a in levels:
        e = a["e2e"]
        print(f"{a['concurrency']:>5} {a['success_rate']:>6.0%} {a['requests_per_sec']:>6} "
              f"{e.get('p50_ms', 0):>8} {e.get('p95_ms', 0):>8} {e.get('p99_ms', 0):>8} "
              f"{a['tokens_per_sec_est_p50'] or 0:>7}")

    if not args.no_json:
        payload = {
            "benchmark": "load_test",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "url": args.url,
            "model": args.model,
            "mode": "fixed_rate" if args.rate else "fixed_concurrency",
            "rate_rps": args.rate,
            "requests_per_level": args.requests,
            "question_classes": classes,
            "warmup": args.warmup,
            "timeout_s": args.timeout,
            "questions": {c: QUESTION_CLASSES[c] for c in classes},
            "prompt_tokens_est_short": count_tokens(QUESTION_CLASSES["short"]),
            "token_estimate_rule": "out_tokens_est = answer_chars // 4 (SSE чата не отдаёт usage; оценка клиентская)",
            "levels": levels,
            "rows": all_rows,
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"load_test{label}")
        print(f"\nСохранено: {paths}")


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
