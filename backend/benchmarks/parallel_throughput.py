"""Aggregate throughput llama.cpp при параллельных слотах (-np 1/2/4).

llama-server делит СУММАРНЫЙ контекст (-c) на слоты (-np): одновременные
запросы обрабатываются параллельно, каждые деля ядра CPU. Замер: N
одновременных стрим-запросов × rounds, агрегатные и по-потоковые метрики
(серверные timings, не клиентские оценки).

Дополнительно: если указан --draft, делается один прогон speculative decoding
и в артефакт пишутся все ключи timings ответа — так фиксируется, отдаёт ли
эта сборка llama.cpp статистику принятия draft-токенов (acceptance rate).

Запуск (из backend/):
    .venv/bin/python benchmarks/parallel_throughput.py --parallel 1 2 4 --rounds 3
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

from benchmarks.metrics import (  # noqa: E402
    command_line,
    git_commit,
    iso_utc,
    save_results,
)

QUESTIONS = [
    "Сколько дней отпуска положено сотруднику?",
    "Какая компенсация за интернет и как её оформить?",
    "Какие тарифы существуют и сколько стоит Бизнес?",
    "Как включить двухфакторную аутентификацию?",
]


async def one_request(port: int, system: str, question: str, max_tokens: int) -> dict:
    import httpx

    t0 = time.perf_counter()
    try:
        r = httpx.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json={"messages": [{"role": "system", "content": system},
                               {"role": "user", "content": question}],
                  "max_tokens": max_tokens, "temperature": 0.2, "cache_prompt": True},
            timeout=600.0,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:160], "wall_ms": round((time.perf_counter() - t0) * 1000, 1)}
    t = data.get("timings") or {}
    u = data.get("usage") or {}
    predicted_ms = t.get("predicted_ms")
    out_tokens = u.get("completion_tokens")
    return {
        "ok": True, "error": None,
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "prefill_ms": t.get("prompt_ms"),
        "tpot_ms": t.get("predicted_per_token_ms"),
        "out_tokens": out_tokens,
        "stream_tok_s": round(out_tokens / (predicted_ms / 1000), 1) if predicted_ms and out_tokens else None,
        "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
    }


def build_prompts() -> list[tuple[str, str]]:
    from app.core import rag

    out = []
    for q in QUESTIONS:
        hits = rag.retrieve(query=q)
        out.append((rag.build_system_prompt(hits, "ru"), q))
    return out


async def amain(args) -> None:
    from benchmarks.local_llamacpp import LlamaServer, MODELS_DIR

    from app.config import get_settings

    get_settings().ensure_dirs()
    from app.core import vectorstore

    if vectorstore._collection().count() == 0:
        from benchmarks.retrieval_eval import build_index

        build_index()
    prompts = build_prompts()

    results = []
    for np in args.parallel:
        gguf = MODELS_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
        with LlamaServer(gguf, ngl=0, ctx=args.ctx, port=args.port, parallel=np) as srv:
            srv.complete("You are helpful.", "Warm-up: say OK.", 8)
            rows: list[dict] = []
            for rnd in range(args.rounds):
                t0 = time.perf_counter()
                batch = await asyncio.gather(*[
                    one_request(args.port, *prompts[i % len(prompts)], args.max_tokens)
                    for i in range(np)
                ])
                wall = time.perf_counter() - t0
                for i, r in enumerate(batch):
                    r.update({"round": rnd, "worker": i})
                rows.extend(batch)
                ok = [r for r in batch if r["ok"]]
                total_out = sum(r["out_tokens"] or 0 for r in ok)
                per_stream = [r["stream_tok_s"] for r in ok if r["stream_tok_s"]]
                print(f"  -np {np} round {rnd}: {len(ok)}/{np} ok wall={wall:.1f}s "
                      f"aggregate={total_out / wall:.1f} tok/s "
                      f"per-stream p50={statistics.median(per_stream) if per_stream else '—'}")
        ok = [r for r in rows if r["ok"]]
        # общий агрегат: все токены уровня / суммарное время всех раундов
        level_wall = sum(r["wall_ms"] for r in rows) / 1000  # приближение; точный агрегат — по раундам ниже
        aggregate = None
        # пересчёт по раундам: Σ out_tokens(раунд) / wall(раунд), затем среднее
        by_round: dict[int, list[dict]] = {}
        for r in rows:
            by_round.setdefault(r["round"], []).append(r)
        per_round = []
        for rnd, batch in sorted(by_round.items()):
            okb = [b for b in batch if b["ok"]]
            outb = sum(b["out_tokens"] or 0 for b in okb)
            # wall уровня недоступен построчно — берём max wall_ms батча как прокси раунда
            wallb = max((b["wall_ms"] for b in batch), default=0) / 1000
            if wallb > 0:
                per_round.append(outb / wallb)
        aggregate = round(statistics.mean(per_round), 1) if per_round else None
        results.append({
            "parallel": np,
            "n_requests": len(rows),
            "n_ok": len(ok),
            "aggregate_tok_s_p50": aggregate,
            "per_stream_tok_s_p50": round(statistics.median(
                [r["stream_tok_s"] for r in ok if r["stream_tok_s"]]), 1) if ok else None,
            "tpot_ms_p50": round(statistics.median(
                [r["tpot_ms"] for r in ok if r["tpot_ms"]]), 1) if ok else None,
            "rows": rows,
        })

    print(f"\n{'np':>4} {'ok':>6} {'agg tok/s':>10} {'per-stream p50':>15} {'tpot p50':>9}")
    for r in results:
        print(f"{r['parallel']:>4} {r['n_ok']}/{r['n_requests']:<4} "
              f"{r['aggregate_tok_s_p50']:>10} {r['per_stream_tok_s_p50']:>15} {r['tpot_ms_p50']:>9}")

    # discovery: отдаёт ли эта сборка статистику speculative decoding
    spec_note = None
    if args.draft:
        gguf = MODELS_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
        from benchmarks.local_llamacpp import LlamaServer

        with LlamaServer(gguf, ngl=0, ctx=args.ctx, port=args.port,
                         draft=MODELS_DIR / args.draft) as srv:
            srv.complete("You are helpful.", "Warm-up: say OK.", 8)
            r = srv.complete(*prompts[0], 64)
            timings_keys = sorted(r.keys())
            spec_note = {"timings_keys": timings_keys,
                         "has_spec_stats": any("spec" in k.lower() or "draft" in k.lower() or "accept" in k.lower()
                                               for k in timings_keys)}
            print(f"\nSpeculative timings discovery: {timings_keys}")

    if not args.no_json:
        payload = {
            "benchmark": "parallel_throughput_llamacpp",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "runtime": f"llama.cpp b11826, CPU -ngl 0, total ctx {args.ctx} (делится на -np слотов)",
            "hardware": "Apple M1 Pro 8-core (6P+2E), 16 GB unified, macOS 13.6",
            "rounds": args.rounds,
            "max_tokens": args.max_tokens,
            "aggregate_note": "aggregate_tok_s = Σ out_tokens батча / max(wall_ms) раунда (прокси по самому долгому запросу)",
            "spec_decode_discovery": spec_note,
            "results": results,
        }
        paths = save_results(payload, "parallel_throughput")
        print(f"\nСохранено: {paths}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--parallel", type=int, nargs="+", default=[1, 2, 4])
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--ctx", type=int, default=16384)
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--port", type=int, default=8126)
    p.add_argument("--draft", default=None, help="draft-модель: discovery spec-статистики")
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    args = p.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
