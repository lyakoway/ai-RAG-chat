"""Prefill/TTFT vs длина контекста: локальный llama.cpp + облачные точки.

Вопрос «как растёт время до первого токена с длиной входа» замеряется двумя
способами:

  --backend llama  — llama-server с Q4_K_M: длины 512→16384 токенов, метрика
      server_prompt_ms (серверный prefill, т.е. локальная компонента TTFT),
      кэш промпта отключён (cache=False), уникальный паддинг на каждый
      повтор (гарантированный cache miss). 32k не запускается: KV-кэш
      ~3.7 ГБ + модель на фоне системного свопа — documented limit.
  --backend zai    — облачные точки 1k/4k/16k: client-observed
      time_to_first_chunk (сеть+очередь+prefill провайдера; для «думающей»
      GLM-5.x включает начало reasoning — НЕ inference TTFT). 1 прогон
      на точку (стоимость ~21k входных токенов ≈ $0.003).

Запуск (из backend/):
    .venv/bin/python benchmarks/context_scaling.py --backend llama
    .venv/bin/python benchmarks/context_scaling.py --backend zai
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

from benchmarks.metrics import (  # noqa: E402
    command_line,
    count_tokens,
    git_commit,
    iso_utc,
    save_results,
)

QUESTION = "Сколько дней отпуска положено сотруднику?"

_WORDS = ("сотрудник отпуск политика документ тариф компенсация интернет рабочее "
          "время удалённый формат оборудование рынок аналитика отчёт квартал "
          "бюджет проект команда встреча задача результат стратегия развитие").split()


def synth_context(target_tokens: int, seed: int) -> str:
    """Связный бессмысленный текст заданной длины (токены tiktoken), seed → уникальность."""
    rng = random.Random(seed)
    parts: list[str] = []
    n_tokens = 0
    while n_tokens < target_tokens:
        sentence = " ".join(rng.choices(_WORDS, k=12)).capitalize() + ". "
        parts.append(sentence)
        n_tokens = count_tokens(" ".join(parts))
    text = " ".join(parts)
    # грубая подгонка: обрезаем по словам, пока не попадём в ±3% целевой длины
    while n_tokens > target_tokens * 1.03 and " " in text:
        text = text[: text.rfind(" ")]
        n_tokens = count_tokens(text)
    return text


def run_llama(args) -> list[dict]:
    from app.core import rag
    from benchmarks.local_llamacpp import LLAMA_DIR, LlamaServer, MODELS_DIR

    gguf = MODELS_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
    hits = rag.retrieve(query=QUESTION)
    system = rag.build_system_prompt(hits, "ru")
    base_tokens = count_tokens(system) + count_tokens(QUESTION)
    print(f"Базовый RAG-промпт: {base_tokens} токенов; длины паддинга: {args.lengths}")

    rows: list[dict] = []
    with LlamaServer(gguf, ngl=args.ngl, ctx=args.ctx, port=args.port) as srv:
        srv.complete("You are helpful.", "Warm-up: say OK.", 8, cache=False)
        for target in args.lengths:
            for rep in range(args.repeats):
                padding = synth_context(target, seed=rep * 100 + target)
                user = f"{padding}\n\nВопрос: {QUESTION}"
                in_tokens = count_tokens(system) + count_tokens(user)
                try:
                    r = srv.complete(system, user, max_tokens=8, cache=False)
                    prefill = r.get("server_prompt_ms")
                    prompt_tokens = r.get("prompt_tokens")
                    err = None
                except Exception as exc:  # noqa: BLE001
                    prefill, prompt_tokens, err = None, None, str(exc)[:160]
                rows.append({
                    "backend": "llama.cpp", "target_tokens": target, "repeat": rep,
                    "in_tokens": in_tokens, "in_tokens_server": prompt_tokens,
                    "prefill_ms": prefill, "error": err,
                })
                print(f"  ~{target:>6} tok (rep{rep}): prefill={prefill}ms "
                      f"server_tokens={prompt_tokens} {'ok' if not err else 'FAIL ' + err}")
    return rows


def run_zai(args) -> list[dict]:
    import asyncio

    from app.core import rag
    from benchmarks.llm_bench import stream_openai_compat

    hits = rag.retrieve(query=QUESTION)
    system = rag.build_system_prompt(hits, "ru")

    async def one(target: int, rep: int) -> dict:
        padding = synth_context(target, seed=rep * 100 + target)
        user = f"{padding}\n\nВопрос: {QUESTION}"
        est = count_tokens(system) + count_tokens(user)
        r = await stream_openai_compat("zai", "glm-5.3-flash", system, user,
                                       max_tokens=16, temperature=0.2, timeout=180.0)
        row = {
            "backend": "zai (client-observed)", "target_tokens": target, "repeat": rep,
            "in_tokens_client_est": est, "in_tokens_server": r.get("in_tokens"),
            "ttfc_ms": r.get("time_to_first_chunk_ms"),
            "ttfc_content_ms": r.get("time_to_first_content_ms"),
            "total_ms": r.get("total_ms"), "error": None if r.get("ok") else r.get("error"),
            "note": "time_to_first_chunk включает reasoning «думающей» модели — не inference TTFT",
        }
        print(f"  ~{target:>6} tok: ttfc={row['ttfc_ms']}ms server_tokens={row['in_tokens_server']}")
        return row

    rows: list[dict] = []
    for target in args.lengths:
        for rep in range(args.repeats):
            rows.append(asyncio.run(one(target, rep)))
            import time as _t
            _t.sleep(1.0)
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    """Агрегат по целевой длине: p50 prefill/ttfc + мс на 1k токенов входа."""
    out: list[dict] = []
    by_len: dict[int, list[dict]] = {}
    for r in rows:
        by_len.setdefault(r["target_tokens"], []).append(r)
    key = "prefill_ms" if rows and rows[0]["backend"] == "llama.cpp" else "ttfc_ms"
    for target in sorted(by_len):
        group = by_len[target]
        vals = [g[key] for g in group if g.get(key) is not None]
        toks = [g.get("in_tokens_server") or g.get("in_tokens_client_est")
                for g in group if g.get(key) is not None]
        toks = [t for t in toks if t]
        mean_tok = statistics.fmean(toks) if toks else None
        out.append({
            "target_tokens": target,
            "n_ok": len(vals),
            f"{key}_p50": round(statistics.median(vals), 1) if vals else None,
            "mean_in_tokens": round(mean_tok, 0) if mean_tok else None,
            "ms_per_1k_tokens": round(statistics.median(vals) / (mean_tok / 1000), 2)
            if vals and mean_tok else None,
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--backend", choices=("llama", "zai"), default="llama")
    p.add_argument("--lengths", type=int, nargs="+",
                   default=[512, 1024, 2048, 4096, 8192, 16384],
                   help="целевые длины паддинга в токенах")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--ctx", type=int, default=20480, help="суммарный контекст llama-server")
    p.add_argument("--ngl", type=int, default=0)
    p.add_argument("--port", type=int, default=8125)
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    args = p.parse_args()

    lengths = [l for l in args.lengths if l <= (args.ctx if args.backend == "llama" else 10**9)]
    if lengths != args.lengths:
        print(f"Длины сверх ctx={args.ctx} пропущены: {[l for l in args.lengths if l > args.ctx]}")

    rows = run_llama(args) if args.backend == "llama" else run_zai(args)
    summary = summarize(rows)
    print(f"\n=== {args.backend}: prefill/ttfc vs длина контекста (p50) ===")
    print(f"{'target tok':>10} {'n_ok':>5} {'p50 ms':>10} {'in tok':>8} {'ms/1k tok':>10}")
    for s in summary:
        p50 = s.get("prefill_ms_p50") if s.get("prefill_ms_p50") is not None else s.get("ttfc_ms_p50")
        cells = [
            f"{p50:>10.0f}" if isinstance(p50, (int, float)) else f"{'—':>10}",
            f"{s['mean_in_tokens']:>8.0f}" if isinstance(s.get("mean_in_tokens"), (int, float)) else f"{'—':>8}",
            f"{s['ms_per_1k_tokens']:>10.2f}" if isinstance(s.get("ms_per_1k_tokens"), (int, float)) else f"{'—':>10}",
        ]
        print(f"{s['target_tokens']:>10} {s['n_ok']:>5} {cells[0]} {cells[1]} {cells[2]}")

    if not args.no_json:
        payload = {
            "benchmark": "context_scaling",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "backend": args.backend,
            "metric_note": (
                "llama: server_prompt_ms — серверный prefill, локальная компонента TTFT; "
                "zai: client-observed time_to_first_chunk (сеть+очередь+prefill+reasoning), "
                "НЕ inference TTFT"
            ),
            "hardware": "Apple M1 Pro, 16 GB unified, macOS 13.6, CPU-only (-ngl 0)",
            "summary": summary,
            "rows": rows,
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"context_scaling_{args.backend}{label}")
        print(f"\nСохранено: {paths}")


if __name__ == "__main__":
    main()
