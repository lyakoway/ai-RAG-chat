# GPU Runbook — vLLM benchmark для AI-RAG-Chat

Готовая инструкция запуска `benchmarks/gpu_vllm.py` на арендованном NVIDIA GPU.
Код бенчмарка и инструкция существуют **до** запуска; самих GPU-цифр в проекте
нет — все поля отчёта помечены **[TODO: run on GPU]** и заполнятся только
фактическим прогоном (см. также [gpu_vllm_summary](artifacts/gpu_vllm_summary.md)).

## 1. Требования

| Компонент | Минимум | Предпочтительно |
|---|---|---|
| GPU | NVIDIA T4 16 GB | A-100 40 GB |
| CUDA / driver | 12.x, свежий драйвер | 12.x |
| Python | 3.10+ | 3.10–3.12 |
| vLLM | последняя, совместимая с CUDA | то же |
| Модель | Qwen2.5-7B-Instruct или GLM-4-9B (доступны в vLLM) | то же |
| Диск | ~20 GB (модель + кэш HF) | 40 GB |
| Время | ~1 ч (сокращённый прогон) | 2–3 ч (полная матрица) |

## 2. Установка (GPU-машина)

```bash
# отдельный environment — vLLM НЕ добавляется в requirements.txt приложения
python3 -m venv vllm-venv && source vllm-venv/bin/activate
pip install vllm psutil          # версия vLLM: последняя для вашей CUDA

# модель
huggingface-cli download Qwen/Qwen2.5-7B-Instruct   # или GLM-4-9B
```

Копия бенчмарка: `backend/benchmarks/gpu_vllm.py` — единственный файл, который
нужен с этой машины (импортирует только стандартные метрики проекта +
OpenAI-совместимый клиент).

## 3. Запуск vLLM-сервера

```bash
# FP16 (baseline) — prefix caching включён по умолчанию в свежих vLLM
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --port 8001 --gpu-memory-utilization 0.85 \
  --max-model-len 8192

# FP8 (если GPU поддерживает: H100/L40S/Ada) — отдельный сервер, другой порт
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct --quantization fp8 \
  --port 8002 --gpu-memory-utilization 0.85 --max-model-len 8192
```

## 4. Бенчмарк

```bash
# установка минимальных зависимостей клиента (если нет)
pip install -r backend/requirements.txt   # или httpx + openai

# конфигурация 1: FP16, concurrency 1 → 4 → 8 → 16
python backend/benchmarks/gpu_vllm.py \
  --base-url http://localhost:8001/v1 \
  --model Qwen/Qwen2.5-7B-Instruct \
  --levels 1 4 8 16 \
  --quantization none --dtype fp16 \
  --vllm-version "$(pip show vllm | grep Version | cut -d' ' -f2)" \
  --label fp16

# конфигурация 2: FP8 (отдельный сервер на :8002 с --quantization fp8)
python backend/benchmarks/gpu_vllm.py \
  --base-url http://localhost:8002/v1 \
  --model Qwen/Qwen2.5-7B-Instruct \
  --levels 1 4 8 16 \
  --quantization fp8 --dtype auto \
  --vllm-version "$(pip show vllm | grep Version | cut -d' ' -f2)" \
  --label fp8

# prefix caching: on — по умолчанию на сервере; off — перезапустить сервер
# с --no-enable-prefix-caching и повторить конфигурацию 1 (--label fp16_noprefix)
```

Артефакты: `backend/results/<ts>_vllm_fp16.json`, `<ts>_vllm_fp8.json`,
`<ts>_vllm_fp16_noprefix.json` — с env-блоком (GPU name, VRAM, driver, CUDA,
vLLM version, quantization, dtype, concurrency levels, prefix caching) и сырыми
per-request latencies (ttft/tpot/total/itl per request) для p50/p95/p99.

## 5. Что измеряется

- **TTFT** p50/p95 (time to first token, из OpenAI-совместимого ответа vLLM);
- **TPOT** p50/p95 (time per output token);
- **throughput** — req/s по уровням concurrency, aggregate tok/s;
- **GPU**: utilization %, VRAM used (MiB) — фоновый опрос nvidia-smi;
- **ошибки**: таймауты, OOM, HTTP ≠ 200 — в `rows[].error`.

## 6. Ожидаемое время и как сократить

- Полная матрица (2 модели квантизации × 4 уровня × ~17 запросов × повторы):
  **2–3 часа**.
- Сокращённый вариант (~1 час): только concurrency **1 и 8**, FP16 vs FP8,
  prefix caching не варьировать (серверный флаг, не клиентский) — сделать
  отдельный вывод в отчёте, что варьировался только серверный запуск.

## 7. Результат

- Заполнить поля **[TODO: run on GPU]** в [gpu_vllm_summary](artifacts/gpu_vllm_summary.md):
  config | TTFT p50 | TPOT p50 | throughput | VRAM | notes.
- Перенести JSON-артефакты в `backend/results/`.
- Обновить §9 в [docs/report-mws-ai.md](report-mws-ai.md) фактическими цифрами
  (структура готова, поля помечены [TODO]).

## 8. Ограничения

- Один GPU, одна модель, короткий прогон — не production-бенчмарк.
- FP8 требует H100/L40S/Ada; на T4 доступен только FP16 (+ int8 weight-only
  через GPTQ/AWQ — отдельный сервер, другой путь квантизации).
- Prefix caching — серверный флаг; клиент его не контролирует, сравнение
  on/off требует перезапуска vLLM-сервера (задокументировать в отчёте).
