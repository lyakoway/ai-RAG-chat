# GPU vLLM benchmark — summary

> **Status: [TODO: run on GPU]** — все поля ниже заполнятся фактическим прогоном
> `backend/benchmarks/gpu_vllm.py` на арендованной GPU-машине по
> [docs/gpu_runbook.md](../gpu_runbook.md). До запуска GPU-цифр в проекте нет.

| Config | TTFT p50 (ms) | TPOT p50 (ms) | Throughput (req/s @ c=8) | VRAM peak (MiB) | Notes |
|---|---|---|---|---|---|
| FP16, c=1 | [TODO: run on GPU] | [TODO] | [TODO] | [TODO] | |
| FP16, c=8 | [TODO] | [TODO] | [TODO] | [TODO] | |
| FP8, c=1 | [TODO] | [TODO] | [TODO] | [TODO] | H100/L40S/Ada only |
| FP8, c=8 | [TODO] | [TODO] | [TODO] | [TODO] | |
| FP16 + prefix caching, shared prefix | [TODO] | [TODO] | [TODO] | [TODO] | server flag, отдельный запуск |
| FP16 без prefix caching | [TODO] | [TODO] | [TODO] | [TODO] | контроль |

- Environment: [TODO: run on GPU] — GPU name, VRAM, CUDA, driver, vLLM version
  (заполняется автоматически в `env`-блоке артефакта).
- Модель: [TODO] (Qwen2.5-7B-Instruct / GLM-4-9B).
- Сравнение с CPU-замерами проекта: [docs/benchmark.md](../benchmark.md) §GPU
  (vLLM-цифры дополнят, не заменят CPU-результаты).
- Raw per-request latencies: `backend/results/<ts>_vllm_*.json` (rows: ttft,
  tpot, total, itl per request — для независимого пересчёта p50/p95/p99).
