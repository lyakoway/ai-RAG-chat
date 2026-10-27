"""Local inference benchmark via llama.cpp (llama-server) on Apple Silicon.

Поднимает llama-server на локальном GGUF, прогоняет RAG-промпты проекта и
собирает ЧЕСТНЫЕ метрики inference (от сервера, не клиентские оценки):
  prompt_ms / prompt_per_token_ms — prefill (это и есть TTFT-компонента runtime)
  predicted_ms / predicted_per_token_ms — генерация (TPOT)
  wall-clock клиента + peak RSS процесса сервера (psutil)

Режимы:
  --bench    Perf-промпты (короткий/длинный контекст) → results/<ts>_local_runtime.json
  --quality  Ответы на answer_queries golden-набора (12) + negative (5) →
             results/<ts>_local_answers.json, дальше:
             .venv/bin/python benchmarks/answer_eval.py --answers-from <файл> --judge zai:glm-5.3-flash

Эксперимент с квантованием: одинаковые прогоны для F16 (baseline) и Q8_0/Q4_K_M
(квантованные) одной модели Llama-3.2-3B-Instruct.

Запуск (из backend/):
    .venv/bin/python benchmarks/local_llamacpp.py --variants Q4_K_M --bench
    .venv/bin/python benchmarks/local_llamacpp.py --variants f16 Q4_K_M --bench --quality
Metal на macOS 13 может крашиться (см. README проекта про Ollama) — при падении
запускайте с --ngl 0 (CPU).
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

LLAMA_DIR = BASE / "benchmarks" / ".llama-cpp" / "llama-b11826"
MODELS_DIR = BASE / "benchmarks" / ".models"
MODEL_BASE = "Llama-3.2-3B-Instruct-{variant}.gguf"

from benchmarks.metrics import (  # noqa: E402
    command_line,
    git_commit,
    iso_utc,
    latency_summary,
    save_results,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--variants", nargs="+", default=["Q4_K_M"],
                   choices=["f16", "Q8_0", "Q4_K_M"], help="какие квантования гонять")
    p.add_argument("--bench", action="store_true", help="perf-промпты (короткий/длинный контекст)")
    p.add_argument("--quality", action="store_true", help="ответы на golden answer/refusal вопросы")
    p.add_argument("--repeats", type=int, default=3, help="повторов на bench-промпт")
    p.add_argument("--ngl", type=int, default=999, help="слоёв на GPU (999=max/Metal, 0=CPU)")
    p.add_argument("--ctx", type=int, default=4096)
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--port", type=int, default=8123)
    p.add_argument("--prefix-cache", action="store_true",
                   help="эксперимент: prefill с общим префиксом (кэш-хит) vs уникальным (промах)")
    p.add_argument("--draft", default=None,
                   help="файл draft-модели в .models/ для speculative decoding (напр. Llama-3.2-1B-Instruct-Q4_K_M.gguf)")
    p.add_argument("--draft-max", type=int, default=8, help="макс. токенов спекуляции на шаг")
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    return p.parse_args()


def wait_ready(port: int, timeout_s: float = 300.0) -> bool:
    """Порт открыт ≠ модель загружена: llama-server слушает /health с 503,
    пока идёт load. Ждём статуса ok."""
    import httpx

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    return False


def swap_used_mb() -> float | None:
    """Фактическое использование swap (macOS): 'used' из sysctl vm.swapusage."""
    try:
        out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True,
                             timeout=5, check=True).stdout
        m = re.search(r"used = ([\d.]+)M", out)
        return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def peak_rss_mb(pid: int) -> float:
    import psutil

    try:
        return psutil.Process(pid).memory_info().rss / (1024 * 1024)
    except psutil.NoSuchProcess:
        return 0.0


class LlamaServer:
    """Контекстный менеджер: поднимает llama-server, отдаёт порт, убивает при выходе."""

    def __init__(self, gguf: Path, ngl: int, ctx: int, port: int,
                 draft: Path | None = None, draft_max: int = 8, parallel: int = 1) -> None:
        self.gguf = gguf
        self.ngl = ngl
        self.ctx = ctx
        self.port = port
        self.draft = draft
        self.draft_max = draft_max
        self.parallel = parallel
        self.proc: subprocess.Popen | None = None
        self.log_lines: list[str] = []
        self.load_time_s: float | None = None  # cold start: от Popen до /health ok

    def __enter__(self) -> "LlamaServer":
        cmd = [
            str(LLAMA_DIR / "llama-server"),
            "-m", str(self.gguf),
            "--port", str(self.port),
            "-ngl", str(self.ngl),
            "-c", str(self.ctx),
            "--no-warmup",
            "--threads", "6",
        ]
        if self.parallel > 1:
            # -c — СУММАРНЫЙ контекст, делится на слоты (n_ctx_slot = c/parallel)
            cmd += ["-np", str(self.parallel)]
        if self.draft:
            # b11826: --draft-max переименован в --spec-draft-n-max; --device none
            # нужен, потому что спекулятивная ветка инициализирует Metal даже при
            # -ngl 0, а Metal на macOS 13 падает (GGML_ASSERT).
            cmd += ["-md", str(self.draft), "--spec-draft-n-max", str(self.draft_max),
                    "--device", "none"]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        t0 = time.perf_counter()
        if not wait_ready(self.port, timeout_s=300):
            out, _ = self.proc.communicate(timeout=5)
            raise RuntimeError(f"llama-server не поднялся:\n{(out or '')[-2000:]}")
        self.load_time_s = round(time.perf_counter() - t0, 2)
        return self

    def __exit__(self, *exc) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def complete(self, system: str, user: str, max_tokens: int, cache: bool = True) -> dict:
        """POST /v1/chat/completions (OpenAI-совместимый), timings берём из ответа
        llama-server (timings.* — серверные метрики prefill/генерации)."""
        import httpx

        r = httpx.post(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                # кэш промпта: включён по умолчанию; отключается для замеров
                # холодного prefill (context_scaling), чтобы повтор не попал в кэш
                "cache_prompt": cache,
            },
            timeout=600.0,
        )
        r.raise_for_status()
        data = r.json()
        timings = data.get("timings") or {}
        usage = data.get("usage") or {}
        choice = (data.get("choices") or [{}])[0]
        predicted_ms = timings.get("predicted_ms")
        completion_tokens = usage.get("completion_tokens")
        return {
            "answer": choice.get("message", {}).get("content", ""),
            "finish_reason": choice.get("finish_reason"),  # stop | length | ...
            "server_prompt_ms": timings.get("prompt_ms"),
            "server_prompt_per_token_ms": timings.get("prompt_per_token_ms"),
            "server_predicted_ms": predicted_ms,
            "server_tpot_ms": timings.get("predicted_per_token_ms"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": completion_tokens,
            "output_tokens_per_sec_gen": round(completion_tokens / (predicted_ms / 1000), 1)
            if predicted_ms and completion_tokens else None,
        }


def build_prompts() -> list[dict]:
    """RAG-промпты из golden_answers: bench-набор + quality-набор."""
    from app.core import rag

    golden = json.loads((BASE / "eval" / "golden_answers.json").read_text(encoding="utf-8"))
    bench_prompts = []
    for p in golden["benchmark_prompts"]:
        hits = rag.retrieve(query=p["q"])
        bench_prompts.append({
            "id": p["id"], "name": p["name"], "q": p["q"],
            "system": rag.build_system_prompt(hits, "ru" if "-ru" in p["name"] else "en"),
            "in_tokens_est": None,
        })
    quality_items = [
        {**item, "kind": "answer"} for item in golden["answer_queries"]
    ] + [{**item, "kind": "refusal"} for item in golden["negative_queries"]]
    quality_prompts = []
    for item in quality_items:
        hits = rag.retrieve(query=item["q"])
        quality_prompts.append({
            "id": item["id"], "kind": item["kind"], "q": item["q"],
            "lang": item.get("lang", "ru"),
            "system": rag.build_system_prompt(hits, item.get("lang", "ru")),
            "retrieved_docs": [h["filename"] for h in hits],
        })
    return bench_prompts, quality_prompts


def main() -> None:
    args = parse_args()
    if not LLAMA_DIR.exists():
        sys.exit(f"llama.cpp не найден: {LLAMA_DIR} (см. docs/benchmark.md)")

    from app.config import get_settings

    get_settings().ensure_dirs()
    from app.core import vectorstore

    if vectorstore._collection().count() == 0:
        print("Индекс пуст — строим демо-пак…")
        from benchmarks.retrieval_eval import build_index

        build_index()

    bench_prompts, quality_prompts = build_prompts()

    all_rows: list[dict] = []
    quality_rows: list[dict] = []
    per_variant_summary: dict[str, dict] = {}

    for variant in args.variants:
        gguf = MODELS_DIR / MODEL_BASE.format(variant=variant)
        if not gguf.exists():
            print(f"!! {gguf.name} отсутствует — пропуск (скачай: docs/benchmark.md)")
            continue
        model_size_gb = round(gguf.stat().st_size / (1024 ** 3), 2)
        print(f"\n=== {variant} ({model_size_gb} GB, ngl={args.ngl}) ===")
        swap_before = swap_used_mb()

        with LlamaServer(gguf, args.ngl, args.ctx, args.port,
                         draft=(MODELS_DIR / args.draft) if args.draft else None,
                         draft_max=args.draft_max) as srv:
            print(f"  cold start (Popen → /health ok): {srv.load_time_s}s"
                  + (f" (draft: {args.draft}, draft-max={args.draft_max})" if args.draft else ""))
            # Warm-up: первый запрос включает загрузку весов в страницы памяти.
            srv.complete("You are helpful.", "Warm-up: say OK.", 8)
            rss_after_warmup = peak_rss_mb(srv.proc.pid)

            # --- bench ---
            if args.bench:
                for prompt in bench_prompts:
                    for rep in range(args.repeats):
                        t0 = time.perf_counter()
                        try:
                            r = srv.complete(prompt["system"], prompt["q"], args.max_tokens)
                            r["ok"] = True
                            r["error"] = None
                        except Exception as exc:  # noqa: BLE001
                            r = {"ok": False, "error": str(exc)[:200], "answer": "",
                                 "finish_reason": None}
                        r["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                        r.update({
                            "variant": variant, "prompt_name": prompt["name"], "repeat": rep,
                            "model_size_gb": model_size_gb, "peak_rss_mb": round(rss_after_warmup, 1),
                            "is_first_request": (prompt is bench_prompts[0] and rep == 0),
                        })
                        all_rows.append(r)
                        print(f"  [{prompt['name']}] prefill={r.get('server_prompt_ms')}ms "
                              f"tpot={r.get('server_tpot_ms')}ms/tok "
                              f"gen={r.get('output_tokens_per_sec_gen')}tok/s "
                              f"finish={r.get('finish_reason')} wall={r['wall_ms']}ms "
                              f"{'ok' if r['ok'] else 'FAIL'}")

            # --- prefix cache: одна переменная — тот же префикс vs уникальный ---
            if args.prefix_cache:
                cache_rows = []
                for rep in range(args.repeats):
                    base = [p for p in bench_prompts if p["name"] == "long-context-ru"]
                    long_sys = base[0]["system"] if base else "You are helpful."
                    for kind, system, user in (
                        ("unique_prefix", long_sys, f"Вопрос {rep}: сколько стоит тариф Старт?"),
                        ("shared_prefix", long_sys, "Какие часы онлайн-доступа?"),
                        ("shared_prefix_again", long_sys, "Что с компенсацией интернета?"),
                    ):
                        try:
                            r = srv.complete(system, user, 16)
                            prefill = r.get("server_prompt_ms")
                        except Exception as exc:  # noqa: BLE001
                            prefill, err = None, str(exc)[:100]
                        else:
                            err = None
                        cache_rows.append({"repeat": rep, "kind": kind,
                                           "prefill_ms": prefill, "error": err})
                        print(f"  [cache:{kind}] prefill={prefill}ms {'ok' if not err else 'FAIL'}")
                # Флаг кэш-хита: предзаполненный префикс «shared_prefix_again»
                # должен пересчитывать только новый вопрос (~десятки токенов).
                hits = [c["prefill_ms"] for c in cache_rows if c["kind"] == "shared_prefix_again" and c["prefill_ms"]]
                misses = [c["prefill_ms"] for c in cache_rows if c["kind"] == "unique_prefix" and c["prefill_ms"]]
                if hits and misses:
                    from benchmarks.metrics import percentile

                    print(f"  → prefill p50: unique={percentile(misses, 50):.0f}ms "
                          f"cache-hit={percentile(hits, 50):.0f}ms")
                if not args.no_json:
                    save_results({
                        "benchmark": "prefix_cache_llamacpp",
                        "date_utc": iso_utc(),
                        "git_commit": git_commit(),
                        "command": command_line(),
                        "runtime": f"llama.cpp b11826, ngl={args.ngl}, ctx={args.ctx}",
                        "model_file": gguf.name,
                        "definition": "unique_prefix — новый system-контекст в каждом слоте; "
                                      "shared_prefix_again — третий подряд запрос с тем же system "
                                      "(префикс уже в кэше, пересчёт только нового вопроса)",
                        "rows": cache_rows,
                    }, f"prefix_cache_{variant.lower()}", fmt=["json"])

            # --- quality ---
            if args.quality:
                for prompt in quality_prompts:
                    t0 = time.perf_counter()
                    try:
                        r = srv.complete(prompt["system"], prompt["q"], args.max_tokens)
                        answer = r["answer"]
                        finish_reason = r.get("finish_reason")
                    except Exception as exc:  # noqa: BLE001
                        answer, finish_reason = "", None
                    quality_rows.append({
                        "question_id": prompt["id"],
                        "kind": prompt["kind"],
                        "lang": prompt["lang"],
                        "question": prompt["q"],
                        "variant": variant,
                        "retrieved_docs": prompt["retrieved_docs"],
                        "answer": answer,
                        "finish_reason": finish_reason,
                        "gen_ms": round((time.perf_counter() - t0) * 1000, 1),
                    })
                    print(f"  [quality:{prompt['kind']}] {prompt['id']}: {len(answer)} chars "
                          f"finish={finish_reason}")

        swap_after = swap_used_mb()
        per_variant_summary[variant] = {
            "model_file": gguf.name,
            "model_size_gb": model_size_gb,
            "load_time_s": srv.load_time_s,
            "peak_rss_mb_after_warmup": round(rss_after_warmup, 1),
            "swap_used_mb_before": swap_before,
            "swap_used_mb_after": swap_after,
            "prefill_ms": latency_summary([r["server_prompt_ms"] for r in all_rows
                                           if r["variant"] == variant and r["ok"]]),
            "prefill_ms_steady": latency_summary([r["server_prompt_ms"] for r in all_rows
                                                  if r["variant"] == variant and r["ok"]
                                                  and not r.get("is_first_request")]),
            "tpot_ms": latency_summary([r["server_tpot_ms"] for r in all_rows
                                        if r["variant"] == variant and r["ok"]]),
            "wall_ms": latency_summary([r["wall_ms"] for r in all_rows
                                        if r["variant"] == variant and r["ok"]]),
            "finish_reasons": sorted({r.get("finish_reason") for r in all_rows
                                      if r["variant"] == variant and r["ok"] and r.get("finish_reason")}),
            "n_errors": sum(1 for r in all_rows if r["variant"] == variant and not r["ok"]),
        }

    print("\n=== Сводка по вариантам (p50) ===")
    print(f"{'variant':<10} {'file GB':>8} {'load s':>7} {'RSS MB':>8} {'swap MB':>8} "
          f"{'prefill p50':>12} {'tpot p50':>10} {'wall p50':>10} {'errs':>5}")
    for v, s in per_variant_summary.items():
        print(f"{v:<10} {s['model_size_gb']:>8} {s['load_time_s']:>7} "
              f"{s['peak_rss_mb_after_warmup']:>8} {s['swap_used_mb_after'] or 0:>8} "
              f"{s['prefill_ms'].get('p50_ms', 0):>12} {s['tpot_ms'].get('p50_ms', 0):>10} "
              f"{s['wall_ms'].get('p50_ms', 0):>10} {s['n_errors']:>5}")

    if not args.no_json and per_variant_summary:
        payload = {
            "benchmark": "local_runtime_llamacpp",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "runtime": f"llama.cpp b11826 (llama-server), ngl={args.ngl}, ctx={args.ctx}, threads=6"
                       + (f", speculative={args.draft} (draft-max={args.draft_max})" if args.draft else ""),
            "model": "meta-llama/Llama-3.2-3B-Instruct (GGUF, bartowski)",
            "hardware": "Apple M1 Pro 8-core, 16 GB unified, macOS 13.6",
            "max_tokens": args.max_tokens,
            "repeats": args.repeats,
            "per_variant": per_variant_summary,
            "rows": all_rows,
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"local_runtime{label}")
        print(f"\nСохранено: {paths}")
    if quality_rows:
        payload = {
            "benchmark": "local_answers_for_eval",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "runtime": f"llama.cpp b11826, ngl={args.ngl}, ctx={args.ctx}",
            "rows": quality_rows,
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"local_answers{label}", fmt=["json"])
        print(f"Ответы для answer_eval: {paths}")


if __name__ == "__main__":
    main()
