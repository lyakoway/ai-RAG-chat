"""LLM benchmark: latency/throughput comparison across providers on one golden set.

Что измеряется на каждый запрос (клиентские часы, один процесс):
  t_connect_ms        — установка TCP+TLS соединения (где доступно)
  time_to_first_chunk_ms — время до первого контентного SSE-чанка. ВАЖНО: для
      облачных API это клиентская оценка (сеть + очередь провайдера + prefill),
      а НЕ TTFT внутреннего inference runtime — тот без телеметрии провайдера
      не измеряется. Для Ollama (локально) честный prompt_eval_time приходит
      от самого сервера.
  itl_ms              — межчанковые интервалы (список, для p50/p95)
  stream_ms           — от первого до последнего чанка
  total_ms            — end-to-end на клиента
  in/out tokens       — из usage API, если провайдер его отдаёт; иначе оценка
      tiktoken cl100k_base (помечается source)
  errors/retries/timeouts — фиксируются на каждый запрос

Провайдеры: zai/openai (OpenAI-совместимый SSE), anthropic, ollama, mock
(провайдер проекта, без сети — sanity-check пайплайна).

Запуск (из backend/):
    .venv/bin/python benchmarks/llm_bench.py --models mock --runs 3
    .venv/bin/python benchmarks/llm_bench.py --models zai:glm-5.3-flash --runs 5 --mode rag
    .venv/bin/python benchmarks/llm_bench.py --models zai:glm-5.3-flash zai:glm-4.5-flash --runs 3 --mode rag
    OLLAMA_NUM_GPU=0 .venv/bin/python benchmarks/llm_bench.py --models ollama:llama3.2:3b --runs 5 --mode rag

Результаты: results/<ts>_llm_bench.json + .csv (сырые по-запросные ряды).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

EVAL_DIR = BASE / "data" / "eval"
os.environ.setdefault("UPLOAD_DIR", str(EVAL_DIR / "uploads"))
os.environ.setdefault("CHROMA_DIR", str(EVAL_DIR / "chroma"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{EVAL_DIR / 'app.db'}")

from benchmarks.metrics import (  # noqa: E402
    command_line,
    count_tokens,
    git_commit,
    iso_utc,
    latency_summary,
    percentile,
    save_results,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--models", nargs="+", required=True, help="id моделей: zai:glm-5.3-flash, ollama:llama3.2:3b, mock…")
    p.add_argument("--runs", type=int, default=3, help="замеров на модель (после warm-up)")
    p.add_argument("--warmup", type=int, default=1, help="прогревочных запросов на модель (в метрики не входят)")
    p.add_argument("--mode", choices=("rag", "raw"), default="rag",
                   help="rag: контекст через retrieval проекта; raw: короткий фиксированный промпт")
    p.add_argument("--max-tokens", type=int, default=512,
                   help="бюджет генерации; для «думающих» GLM-5.x часть уходит на reasoning-токены")
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=120.0, help="таймаут одного запроса, с")
    p.add_argument("--prompt-set", default="all", choices=("all", "short", "long"))
    p.add_argument("--price-input", type=float, default=None,
                   help="USD за 1M входных токенов (для cost_per_request; только при measured usage)")
    p.add_argument("--price-output", type=float, default=None,
                   help="USD за 1M выходных токенов")
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    return p.parse_args()


# ------------------------------------------------------------------ API --

def split_model_id(model_id: str) -> tuple[str, str]:
    provider, _, model = model_id.partition(":")
    return provider, model or model_id


async def stream_openai_compat(provider: str, model: str, system: str, user: str,
                               max_tokens: int, temperature: float, timeout: float) -> dict:
    """SSE-стрим OpenAI-совместимого API с таймстампами чанков и опциональным usage.

    usage запрашивается через stream_options.include_usage; если провайдер
    отвечает 400 (не поддерживает), повторяем без него — и помечаем usage как
    недоступный. Возвращает тайминги + счётчики токенов с указанием источника.
    """
    from app.config import get_settings

    settings = get_settings()
    if provider == "zai":
        api_key, base_url = settings.zai_api_key, "https://api.z.ai/api/paas/v4"
    elif provider == "openai":
        api_key, base_url = settings.openai_api_key, None
    else:
        raise ValueError(f"unsupported provider {provider}")
    if not api_key:
        raise RuntimeError(f"no API key for {provider}")

    import httpx

    body: dict = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # GLM: «думающие» поколения требуют thinking.enabled (см. app/llm/providers.py).
    if provider == "zai":
        wanted = settings.zai_thinking.lower()
        if "glm-5" in model.lower():
            body["thinking"] = {"type": "enabled", "level": "low"} if wanted in ("disabled", "") \
                else {"type": "enabled", **({"level": wanted} if wanted != "enabled" else {})}
        elif wanted in ("disabled", ""):
            body["thinking"] = {"type": "disabled"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"

    result: dict = {"usage": None, "retries": 0}
    for attempt in (1, 2):
        t0 = time.perf_counter()
        chunk_ts: list[float] = []       # content-чанки (видимый пользователю текст)
        reasoning_ts: list[float] = []   # reasoning_content-чанки (GLM-5.x «думающие»)
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            payload = {**body, **({"stream_options": {"include_usage": True}} if attempt == 1 else {})}
            timeout_conf = httpx.Timeout(connect=15.0, read=timeout, write=30.0, pool=15.0)
            async with httpx.AsyncClient(timeout=timeout_conf) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        err_text = (await resp.aread()).decode(errors="replace")[:300]
                        if resp.status_code == 400 and attempt == 1:
                            result["retries"] += 1
                            continue  # вероятно, stream_options не поддержан
                        raise RuntimeError(f"HTTP {resp.status_code}: {err_text}")
                    event_buf = ""
                    async for raw in resp.aiter_lines():
                        if raw.startswith(":"):
                            continue
                        if raw.startswith("data:"):
                            event_buf += raw[5:].strip()
                            continue
                        if raw.strip() or not event_buf:
                            continue
                        data = event_buf
                        event_buf = ""
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("usage"):
                            result["usage"] = obj["usage"]
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if choices[0].get("finish_reason"):
                            result["finish_reason"] = choices[0]["finish_reason"]
                        if delta.get("content"):
                            chunk_ts.append(time.perf_counter())
                            text_parts.append(delta["content"])
                        if delta.get("reasoning_content"):
                            reasoning_ts.append(time.perf_counter())
                            reasoning_parts.append(delta["reasoning_content"])
            break
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:  # noqa: BLE001
            if attempt == 1:
                result["retries"] += 1
                result.setdefault("first_error", str(exc))
                await asyncio.sleep(1.0)
                continue
            raise

    return _finalize(result, chunk_ts, "".join(text_parts), system, user, t0,
                     first_stream_ts=(reasoning_ts + chunk_ts)[:1] or None,
                     reasoning_stats={
                         "reasoning_chunks": len(reasoning_ts),
                         "reasoning_ms_first_to_last": round((reasoning_ts[-1] - reasoning_ts[0]) * 1000, 1)
                         if len(reasoning_ts) > 1 else 0.0,
                     } if reasoning_ts else None)


async def stream_anthropic(model: str, system: str, user: str,
                           max_tokens: int, temperature: float, timeout: float) -> dict:
    from app.config import get_settings

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key,
                            timeout=__import__("httpx").Timeout(timeout), max_retries=1)
    result: dict = {"usage": None, "retries": 0}
    t0 = time.perf_counter()
    chunk_ts: list[float] = []
    text_parts: list[str] = []
    async with client.messages.stream(
        model=model, system=system, messages=[{"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=temperature,
    ) as stream:
        async for text in stream.text_stream:
            chunk_ts.append(time.perf_counter())
            text_parts.append(text)
        final = stream.get_final_message()
        result["usage"] = {
            "prompt_tokens": final.usage.input_tokens,
            "completion_tokens": final.usage.output_tokens,
        }
    return _finalize(result, chunk_ts, "".join(text_parts), system, user, t0)


async def stream_ollama(model: str, system: str, user: str,
                        max_tokens: int, temperature: float, timeout: float) -> dict:
    """Ollama /api/chat: последний чанк (done=true) несёт честные метрики
    inference-сервера: prompt_eval_duration (prefill→TTFT), eval_duration и
    eval_count (генерация), prompt_eval_count (входные токены)."""
    from app.config import get_settings

    settings = get_settings()
    import httpx

    payload = {
        "model": model, "stream": True,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    if settings.ollama_num_gpu is not None:
        payload["options"]["num_gpu"] = settings.ollama_num_gpu

    result: dict = {"usage": None, "retries": 0, "server_stats": None}
    t0 = time.perf_counter()
    chunk_ts: list[float] = []
    text_parts: list[str] = []
    timeout_conf = httpx.Timeout(connect=10.0, read=timeout, write=60.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout_conf) as client:
        async with client.stream("POST", f"{settings.ollama_base_url}/api/chat", json=payload) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {(await resp.aread()).decode()[:200]}")
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = (data.get("message") or {}).get("content")
                if token:
                    chunk_ts.append(time.perf_counter())
                    text_parts.append(token)
                if data.get("done"):
                    result["server_stats"] = {
                        # всё в наносекундах в API Ollama
                        "prompt_eval_ns": data.get("prompt_eval_duration"),
                        "eval_ns": data.get("eval_duration"),
                        "prompt_eval_count": data.get("prompt_eval_count"),
                        "eval_count": data.get("eval_count"),
                        "total_ns": data.get("total_duration"),
                        "load_ns": data.get("load_duration"),
                    }
                    result["usage"] = {
                        "prompt_tokens": data.get("prompt_eval_count"),
                        "completion_tokens": data.get("eval_count"),
                    }
    return _finalize(result, chunk_ts, "".join(text_parts), system, user, t0)


async def stream_mock(provider_inst, system: str, user: str) -> dict:
    result: dict = {"usage": None, "retries": 0}
    t0 = time.perf_counter()
    chunk_ts: list[float] = []
    text_parts: list[str] = []
    async for delta in provider_inst.stream(system, [type("M", (), {"role": "user", "content": user})()]):
        chunk_ts.append(time.perf_counter())
        text_parts.append(delta)
    return _finalize(result, chunk_ts, "".join(text_parts), system, user, t0)


def _finalize(result: dict, chunk_ts: list[float], answer: str,
              system: str, user: str, t0: float,
              first_stream_ts: list[float] | None = None,
              reasoning_stats: dict | None = None) -> dict:
    now = time.perf_counter()
    t_total = (now - t0) * 1000
    # Первый чанк генерации любого типа (для «думающих» моделей это reasoning);
    # для провайдеров без reasoning — это первый content-чанк.
    t_first_generated = (first_stream_ts[0] - t0) * 1000 if first_stream_ts else (
        (chunk_ts[0] - t0) * 1000 if chunk_ts else None
    )
    # Первый ВИДИМЫЙ пользователю контентный чанк — то, что видит клиент UI.
    t_first_content = (chunk_ts[0] - t0) * 1000 if chunk_ts else None
    itl = [(b - a) * 1000 for a, b in zip(chunk_ts, chunk_ts[1:])]
    usage = result.get("usage")
    out_tokens = usage.get("completion_tokens") if usage else count_tokens(answer)
    in_tokens = usage.get("prompt_tokens") if usage else count_tokens(system) + count_tokens(user)
    stream_ms = (chunk_ts[-1] - chunk_ts[0]) * 1000 if len(chunk_ts) > 1 else 0.0
    return {
        **{k: v for k, v in result.items() if k != "usage"},
        "usage_raw": usage,  # сырой usage API сохраняется в артефакте
        "finish_reason": result.get("finish_reason"),
        "time_to_first_chunk_ms": round(t_first_generated, 1) if t_first_generated is not None else None,
        "time_to_first_content_ms": round(t_first_content, 1) if t_first_content is not None else None,
        "stream_ms": round(stream_ms, 1),
        "total_ms": round(t_total, 1),
        "chunks": len(chunk_ts),
        "reasoning": reasoning_stats,
        "itl_ms_p50": round(percentile(itl, 50), 2) if itl else None,
        "itl_ms_p95": round(percentile(itl, 95), 2) if itl else None,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "tokens_source": "usage" if usage else "tiktoken-estimate",
        "output_tokens_per_sec_stream": round(out_tokens / (stream_ms / 1000), 1)
        if usage and stream_ms > 0 and out_tokens else None,
        "answer": answer,
        "answer_chars": len(answer),
    }


# ----------------------------------------------------------------- prompts --

def build_prompts(mode: str, prompt_set: str) -> list[dict]:
    """Промпты для замера. rag — контекст через retrieval проекта на демо-паке."""
    golden = json.loads((BASE / "eval" / "golden_answers.json").read_text(encoding="utf-8"))
    wanted = {"all": None, "short": "short", "long": "long"}[prompt_set]

    from app.core import rag

    prompts = []
    for p in golden["benchmark_prompts"]:
        if wanted and p.get("context_size") != wanted:
            continue
        if mode == "rag":
            hits = rag.retrieve(query=p["q"])
            system = rag.build_system_prompt(hits, "ru" if "ru" in p["name"] else "en")
            retrieval_ms = None  # замеряется на живом прогоне в main
            doc_hint = p["doc_hint"]
            top_docs = [h["filename"] for h in hits]
        else:
            system = "You are a helpful assistant. Answer concisely."
            retrieval_ms = None
            doc_hint = None
            top_docs = []
        prompts.append({
            "id": p["id"], "name": p["name"], "system": system, "user": p["q"],
            "context_size": p.get("context_size", "short"),
            "target_answer_tokens": p.get("target_answer_tokens", 150),
            "doc_hint": doc_hint, "retrieved_docs": top_docs,
        })
    return prompts


async def bench_one(model_id: str, prompt: dict, args) -> dict:
    provider_name, model = split_model_id(model_id)
    kwargs = dict(max_tokens=args.max_tokens, temperature=args.temperature, timeout=args.timeout)
    try:
        if provider_name in ("zai", "openai"):
            r = await stream_openai_compat(provider_name, model, prompt["system"], prompt["user"], **kwargs)
        elif provider_name == "anthropic":
            r = await stream_anthropic(model, prompt["system"], prompt["user"], **kwargs)
        elif provider_name == "ollama":
            r = await stream_ollama(model, prompt["system"], prompt["user"], **kwargs)
        elif provider_name == "mock":
            from app.llm.providers import MockProvider

            r = await stream_mock(MockProvider(), prompt["system"], prompt["user"])
        else:
            raise ValueError(f"unknown provider {provider_name}")
        r.update({"ok": True, "error": None})
    except Exception as exc:  # noqa: BLE001
        r = {
            "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "retries": 0,
            "finish_reason": None,
            "time_to_first_chunk_ms": None, "time_to_first_content_ms": None,
            "stream_ms": None, "total_ms": None,
            "chunks": 0, "reasoning": None,
            "itl_ms_p50": None, "itl_ms_p95": None,
            "in_tokens": None, "out_tokens": None, "tokens_source": None,
            "output_tokens_per_sec_stream": None, "answer": "", "answer_chars": 0,
            "usage": None,
        }
    cost = None
    u = r.get("usage_raw") or r.get("usage")
    if u and args.price_input is not None and args.price_output is not None:
        cost = round(
            (u.get("prompt_tokens") or 0) / 1e6 * args.price_input
            + (u.get("completion_tokens") or 0) / 1e6 * args.price_output, 7
        )
    r.update({
        "model_id": model_id, "provider": provider_name, "model": model,
        "prompt_name": prompt["name"], "prompt_id": prompt["id"],
        "mode": args.mode, "max_tokens": args.max_tokens, "temperature": args.temperature,
        "context_size": prompt["context_size"],
        "prompt_tokens_client_est": count_tokens(prompt["system"]) + count_tokens(prompt["user"]),
        "cost_usd": cost,
    })
    return r


def aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["ok"]]
    ttf = [r["time_to_first_chunk_ms"] for r in ok if r["time_to_first_chunk_ms"] is not None]
    ttf_content = [r["time_to_first_content_ms"] for r in ok if r.get("time_to_first_content_ms") is not None]
    totals = [r["total_ms"] for r in ok if r["total_ms"] is not None]
    streams = [r["stream_ms"] for r in ok if r["stream_ms"]]
    tps = [r["output_tokens_per_sec_stream"] for r in ok if r["output_tokens_per_sec_stream"]]
    out_tok = [r["out_tokens"] for r in ok if r["out_tokens"]]
    agg = {
        "n_requests": len(rows), "n_ok": len(ok),
        "n_errors": len(rows) - len(ok),
        "ttft_summary": latency_summary(ttf),
        "ttft_content_summary": latency_summary(ttf_content),
        "e2e_summary": latency_summary(totals),
        "stream_summary": latency_summary(streams),
        "output_tokens_per_sec": {k: v for k, v in {
            "mean": round(statistics.fmean(tps), 1) if tps else None,
            "p50": round(percentile(tps, 50), 1) if tps else None,
        }.items() if v is not None},
        "out_tokens_mean": round(statistics.fmean(out_tok), 1) if out_tok else None,
        "tokens_source": sorted({r["tokens_source"] for r in ok if r["tokens_source"]}),
        "finish_reasons": {
            fr: sum(1 for r in ok if r.get("finish_reason") == fr)
            for fr in sorted({r.get("finish_reason") for r in ok if r.get("finish_reason")})
        },
        "cost_usd_mean": round(statistics.fmean([r["cost_usd"] for r in ok if r.get("cost_usd") is not None]), 7)
        if any(r.get("cost_usd") is not None for r in ok) else None,
        "errors": [r["error"] for r in rows if not r["ok"]][:5],
    }
    return agg


async def main_async(args) -> None:
    from app.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    # RAG-режим требует индекс: собираем его один раз в изолированном хранилище.
    if args.mode == "rag":
        from app.core import vectorstore

        if vectorstore._collection().count() == 0:
            print("Индекс пуст — строим демо-пак в data/eval…")
            from benchmarks.retrieval_eval import build_index

            build_index()

    prompts = build_prompts(args.mode, args.prompt_set)
    print(f"Промптов: {len(prompts)} | runs={args.runs} | warmup={args.warmup} | mode={args.mode}")

    all_rows: list[dict] = []
    per_model = {}
    for model_id in args.models:
        print(f"\n=== {model_id} ===")
        model_rows: list[dict] = []
        for i in range(args.warmup + args.runs):
            for prompt in prompts:
                is_warmup = i < args.warmup
                t0 = time.perf_counter()
                retrieval_ms = None
                if args.mode == "rag":
                    from app.core import rag

                    tr = time.perf_counter()
                    hits = rag.retrieve(query=prompt["user"])
                    retrieval_ms = round((time.perf_counter() - tr) * 1000, 2)
                    prompt = {**prompt, "retrieved_docs": [h["filename"] for h in hits]}
                r = await bench_one(model_id, prompt, args)
                r["is_warmup"] = is_warmup
                r["retrieval_ms"] = retrieval_ms
                if args.mode == "rag" and r.get("ok"):
                    r["e2e_with_retrieval_ms"] = round((r["total_ms"] or 0) + (retrieval_ms or 0), 1)
                tag = "warmup" if is_warmup else f"run{i - args.warmup + 1}"
                ttf = r.get("time_to_first_chunk_ms")
                print(f"  [{tag}] {prompt['name']:<18} "
                      f"ttfc={ttf if ttf is not None else 'ERR'}ms "
                      f"total={r.get('total_ms')}ms out={r.get('out_tokens')}tok "
                      f"{'ok' if r.get('ok') else 'FAIL: ' + str(r.get('error'))[:80]}")
                if not is_warmup:
                    model_rows.append(r)
                    all_rows.append(r)
        per_model[model_id] = aggregate(model_rows)
        a = per_model[model_id]
        ttf = a["ttft_summary"].get("p50_ms")
        print(f"  → p50 ttfc={ttf}ms | p50 e2e={a['e2e_summary'].get('p50_ms')}ms | "
              f"tok/s={a['output_tokens_per_sec'].get('p50')} | ok={a['n_ok']}/{a['n_requests']}")

    payload = {
        "benchmark": "llm_bench",
        "date_utc": iso_utc(),
        "git_commit": git_commit(),
        "command": command_line(),
        "mode": args.mode,
        "runs_per_prompt": args.runs,
        "warmup_per_model": args.warmup,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "timeout_s": args.timeout,
        "price_input_usd_per_1m": args.price_input,
        "price_output_usd_per_1m": args.price_output,
        "hardware_client": "Apple M1 Pro, 16 GB, macOS 13.6 (клиентские часы одного процесса)",
        "ttft_definition": "time_to_first_chunk — клиентская оценка: сеть + очередь + prefill провайдера; "
                           "не является TTFT inference runtime. Для ollama честные метрики сервера в server_stats.",
        "per_model": per_model,
        "rows": sorted(all_rows, key=lambda r: (r["model_id"], r["prompt_id"])),
    }
    print("\n=== Сводка (p50, без warm-up) ===")
    print(f"{'model':<28} {'ttfc p50':>9} {'ttfc p95':>9} {'content p50':>11} {'e2e p50':>9} {'tok/s':>7} {'ok':>5}")
    for mid, a in per_model.items():
        print(f"{mid:<28} {a['ttft_summary'].get('p50_ms', 0):>9} {a['ttft_summary'].get('p95_ms', 0):>9} "
              f"{a['ttft_content_summary'].get('p50_ms', 0):>11} "
              f"{a['e2e_summary'].get('p50_ms', 0):>9} "
              f"{a['output_tokens_per_sec'].get('p50') or 0:>7} {a['n_ok']}/{a['n_requests']}")
    if not args.no_json:
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"llm_bench{label}")
        print(f"\nСохранено: {paths}")


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
