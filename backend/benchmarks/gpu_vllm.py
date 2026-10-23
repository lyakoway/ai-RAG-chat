"""GPU vLLM benchmark — ПОДГОТОВЛЕН, НО НЕ ЗАПУСКАЛСЯ.

СТАТУС: на машине разработки нет NVIDIA GPU (Apple M1 Pro, macOS 13.6; Metal
крашится в llama.cpp, MLX не ставится). Этот скрипт — воспроизводимый сценарий
для GPU-машины; ни одна цифра из него не включена в результаты проекта.

Что делает (на машине с NVIDIA GPU + CUDA):
  1. Ожидает работающий vLLM OpenAI-совместимый сервер (запуск — см. ниже).
  2. Прогоняет concurrency-уровни 1/2/4/8 на тех же RAG-промптах golden_answers.json.
  3. Собирает на каждый запрос: TTFT (первый чанк стрима; в vLLM это фактический
     первый сгенерированный токен — сервер не батчит SSE-чанки), ITL, TPOT из
     usage, e2e; перцентили p50/p95/p99.
  4. Параллельно опрашивает nvidia-smi (GPU utilization, memory.used) и
     фиксирует пиковое потребление VRAM, OOM и таймауты.

Запуск на GPU-машине:
    pip install vllm psutil
    python -m vllm.entrypoints.openai.api_server \
        --model meta-llama/Llama-3.2-3B-Instruct --max-model-len 8192 \
        --gpu-memory-utilization 0.85 --port 8001
    python benchmarks/gpu_vllm.py --base-url http://localhost:8001/v1 \
        --model meta-llama/Llama-3.2-3B-Instruct --levels 1 2 4 8 --requests 16

Непроверенные части (нет GPU): совместимость версий vLLM, фактические числа
TTFT/TPOT/throughput, поведение KV-cache при росте конкурентности, влияние
gpu-memory-utilization на пиковую VRAM.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base-url", default="http://localhost:8001/v1")
    p.add_argument("--model", required=True, help="имя модели, как она загружена в vLLM")
    p.add_argument("--levels", type=int, nargs="+", default=[1, 2, 4, 8])
    p.add_argument("--requests", type=int, default=16, help="запросов на уровень")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--gpu-poll-s", type=float, default=1.0)
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    return p.parse_args()


def build_prompts() -> list[dict]:
    """Те же RAG-промпты, что и в llm_bench/local_llamacpp — сопоставимо с CPU-прогонами."""
    from app.core import rag

    golden = json.loads((BASE / "eval" / "golden_answers.json").read_text(encoding="utf-8"))
    out = []
    for p in golden["benchmark_prompts"]:
        hits = rag.retrieve(query=p["q"])
        out.append({
            "id": p["id"], "name": p["name"], "q": p["q"],
            "system": rag.build_system_prompt(hits, "ru" if "-ru" in p["name"] else "en"),
        })
    return out


async def stream_once(client, args, prompt: dict) -> dict:
    """Один стрим-запрос к vLLM; vLLM шлёт по чанку на токен, поэтому
    клиентские ITL здесь достоверны (в отличие от облачных провайдеров)."""
    import httpx

    t0 = time.perf_counter()
    chunk_ts: list[float] = []
    text_parts: list[str] = []
    usage = None
    finish_reason = None
    try:
        async with client.stream(
            "POST", f"{args.base_url}/chat/completions",
            json={
                "model": args.model,
                "messages": [
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["q"]},
                ],
                "stream": True, "temperature": args.temperature, "max_tokens": args.max_tokens,
                "stream_options": {"include_usage": True},
            },
            timeout=httpx.Timeout(connect=10.0, read=args.timeout, write=30.0, pool=10.0),
        ) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {(await resp.aread())[:200]}")
            buf = ""
            async for raw in resp.aiter_lines():
                if raw.startswith("data:"):
                    buf += raw[5:].strip()
                    continue
                if raw.strip() or not buf:
                    continue
                data, buf = buf, ""
                if data == "[DONE]":
                    break
                obj = json.loads(data)
                if obj.get("usage"):
                    usage = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    chunk_ts.append(time.perf_counter())
                    text_parts.append(delta)
        err = None
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"[:250]

    now = time.perf_counter()
    itl = [(b - a) * 1000 for a, b in zip(chunk_ts, chunk_ts[1:])]
    stream_ms = (chunk_ts[-1] - chunk_ts[0]) * 1000 if len(chunk_ts) > 1 else 0.0
    out_tokens = (usage or {}).get("completion_tokens") or count_tokens("".join(text_parts))
    return {
        "prompt_name": prompt["name"], "ok": err is None, "error": err,
        "ttft_ms": round((chunk_ts[0] - t0) * 1000, 1) if chunk_ts else None,
        "stream_ms": round(stream_ms, 1),
        "total_ms": round((now - t0) * 1000, 1),
        "itl_ms_p50": round(percentile(itl, 50), 2) if itl else None,
        "tpot_ms": round(stream_ms / max(out_tokens - 1, 1), 2) if out_tokens > 1 and stream_ms else None,
        "in_tokens": (usage or {}).get("prompt_tokens"),
        "out_tokens": out_tokens,
        "output_tokens_per_sec": round(out_tokens / (stream_ms / 1000), 1) if stream_ms and out_tokens else None,
        "finish_reason": finish_reason,
    }


async def poll_gpu(interval_s: float):
    """Фоновый опрос nvidia-smi: utilization.gpu, memory.used (MiB)."""
    samples = []
    try:
        while True:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5).stdout.strip()
                util, mem = out.splitlines()[0].split(", ")
                samples.append({"ts": time.perf_counter(), "gpu_util_percent": int(util),
                                "vram_used_mib": int(mem)})
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        return samples


async def run_level(level: int, n_requests: int, args, prompts: list[dict]) -> tuple[dict, list[dict]]:
    import httpx

    sem = asyncio.Semaphore(level)

    async def bounded(prompt):
        async with sem:
            async with httpx.AsyncClient() as client:
                return await stream_once(client, args, prompt)

    monitor = asyncio.create_task(poll_gpu(args.gpu_poll_s))
    t0 = time.perf_counter()
    tasks = []
    for i in range(n_requests):
        tasks.append(asyncio.create_task(bounded(prompts[i % len(prompts)])))
    rows = await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0
    monitor.cancel()
    try:
        samples = await monitor
    except Exception:  # noqa: BLE001
        samples = []

    ok = [r for r in rows if r["ok"]]
    agg = {
        "concurrency": level,
        "n_requests": n_requests,
        "n_ok": len(ok),
        "wall_s": round(wall, 2),
        "requests_per_sec": round(n_requests / wall, 3),
        "ttft_ms": latency_summary([r["ttft_ms"] for r in ok if r["ttft_ms"] is not None]),
        "tpot_ms": latency_summary([r["tpot_ms"] for r in ok if r["tpot_ms"] is not None]),
        "e2e_ms": latency_summary([r["total_ms"] for r in ok]),
        "output_tokens_per_sec_p50": percentile(
            [r["output_tokens_per_sec"] for r in ok if r["output_tokens_per_sec"]], 50),
        "gpu_util_percent_mean": round(
            sum(s["gpu_util_percent"] for s in samples) / len(samples), 1) if samples else None,
        "vram_used_mib_max": max((s["vram_used_mib"] for s in samples), default=None),
        "errors": [r["error"] for r in rows if not r["ok"]][:5],
    }
    return agg, rows


async def main_async(args) -> None:
    import httpx

    try:
        r = httpx.get(f"{args.base_url}/models", timeout=10.0)
        print(f"vLLM {args.base_url}: HTTP {r.status_code}")
        assert r.status_code == 200
    except Exception as exc:  # noqa: BLE001
        print(f"vLLM-сервер недоступен: {exc}\nЗапусти: python -m vllm.entrypoints.openai.api_server --model …")
        sys.exit(2)

    from app.config import get_settings

    get_settings().ensure_dirs()
    from app.core import vectorstore

    if vectorstore._collection().count() == 0:
        from benchmarks.retrieval_eval import build_index

        build_index()

    prompts = build_prompts()
    levels = []
    all_rows = []
    for level in args.levels:
        print(f"=== concurrency={level} ===")
        agg, rows = await run_level(level, args.requests, args, prompts)
        for row in rows:
            row["concurrency"] = level
        all_rows.extend(rows)
        levels.append(agg)
        print(f"  ok={agg['n_ok']}/{agg['n_requests']} rps={agg['requests_per_sec']} "
              f"ttft p50={agg['ttft_ms'].get('p50_ms')}ms tpot p50={agg['tpot_ms'].get('p50_ms')}ms "
              f"gpu={agg['gpu_util_percent_mean']}% vram_max={agg['vram_used_mib_max']}MiB")

    if not args.no_json:
        payload = {
            "benchmark": "gpu_vllm",
            "status": "executed",  # менять на 'prepared_not_executed' не требуется: файл появляется только после реального запуска
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "runtime": f"vLLM OpenAI-compatible server @ {args.base_url}",
            "model": args.model,
            "levels": levels,
            "rows": all_rows,
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"gpu_vllm{label}")
        print(f"\nСохранено: {paths}")


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
