# Reproduce — как воспроизвести измерения проекта

Единая шпаргалка команд. Формат: команда → ожидаемый артефакт → где смотреть
результат. Полная методика — [docs/benchmark.md](benchmark.md); этот файл —
только команды. Все eval/benchmark-команды выполняются из `backend/` с
`WORKSPACE_AUTH_MODE=demo` (CLI-инструменты работают с workspace `default`;
strict-режим приложения требует `WORKSPACE_TOKENS` и падает на старте без него —
это fail fast, не ошибка).

## 1. Установка

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # приложение
pip install -r requirements-dev.txt      # тесты (pytest, reportlab)
cp .env.example .env                     # ключи опциональны (mock-режим работает без них)
```

`.env` (все опциональны кроме случаев strict): `ZAI_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY` — LLM-провайдеры; `WORKSPACE_AUTH_MODE=strict|demo`
(default strict; strict требует `WORKSPACE_TOKENS=token=ws,…`);
`WORKSPACE_AUTH_MODE=demo` — единый workspace `default` без токена (локальная
разработка и CLI-инструменты ниже).

## 2. Запуск приложения

```bash
cd backend
WORKSPACE_AUTH_MODE=demo .venv/bin/uvicorn app.main:app --reload --port 8000
```

Проверка: `curl http://localhost:8000/api/health` → `{"status": "ok", …}`.
Демо-документы: `curl -X POST http://localhost:8000/api/documents/demo`.

## 3. Тесты

```bash
cd backend
.venv/bin/pytest -q                # полный suite (260; ~15–20 с, сеть не нужна)
```

Результат: `260 passed`. Live-API тестов в suite нет (маркер `live` в
pytest.ini зарезервирован и исключён по умолчанию: `-m 'not live'`).

## 4. Retrieval evaluation (dense / bm25 / hybrid)

Источник: `benchmarks/retrieval_eval.py`; held-out набор — 47 запросов
(`eval/golden_retrieval.json`).

```bash
cd backend
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/retrieval_eval.py --strategy all --repeats 3
```

Артефакт: `results/<ts>_retrieval_all.json` + `.csv` (сырые по-запросные ряды,
git commit, команда, sha256 датасета, версии зависимостей).
Ожидаемые метрики (bit-стабильны между прогонами): hybrid **R@1 0.8723, R@3
0.9787, MRR@5 0.9255, nDCG@5 0.9395**; dense R@1 0.5319; bm25 R@1 0.8723.

## 5. Reranker evaluation (отклонённая альтернатива, ADR-002)

Источник: `benchmarks/reranker_eval.py`; CPU ONNX ~1 GB (первый запуск качает
модель), кандидаты hybrid top-20 → rerank → top-5.

```bash
cd backend
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/reranker_eval.py
```

Артефакт: `results/<ts>_reranker.json` (+ csv). Ожидаемо: Recall@1 ≈ 0.617,
rerank p50 ≈ 6–7 s (метрика деградации — основание отказа, см. ADR-002).

### Если цифры отличаются от ожидаемых (§4–§5)

- Проверь sha256 held-out набора в артефакте (`eval/golden_retrieval.json`) —
  совпадает с `env.golden_set_sha256` в твоём артефакте?
- Версия fastembed и embedding-модели — поле `env.dependencies` в артефакте.
- Параметры: RRF k=60, top-k, стратегия — поле `command` в артефакте.
- Если всё совпадает, а метрики другие — сравни с эталонными артефактами в
  `results/` (закоммичены как reference).
- Не «подгоняй» цифры: расхождение — либо окружение, либо реальный баг; в
  обоих случаях зафиксируй и разберись, не правь метрики.

## 6. Answer evaluation (live GLM — платный API)

Источник: `benchmarks/answer_eval.py`; требует `ZAI_API_KEY` в `backend/.env`.
Стоимость: ~17 запросов answer+judge на прогон (копейки, но не ноль).

```bash
cd backend
# held-out v2 (8 answer + 3 negative): ответы GLM-5.3-flash + судья GLM-4.5-flash
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/answer_eval.py \
  --model zai:glm-5.3-flash --judge zai:glm-4.5-flash --golden golden_answers_v2.json
# бесплатная переоценка сохранённых ответов (без LLM):
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/answer_eval.py \
  --answers-from ../results/<файл>_local_answers_*.json --golden golden_answers_v2.json --no-judge
```

Артефакт: `results/<ts>_answer_eval_*.json` (+ csv). Ожидаемо (held-out v2,
GLM-5.3-flash): correctness 1.0, citations 8/8, refusal 3/3 — **выборка мала
(8+3), направление, не доказательство**.

## 7. Миграция SQL (workspace backfill + NOT NULL)

Источник: `app/db/migrate.py`. Backup + lock + отчёт JSON + no-op при повторе.
Боевая база уже мигрирована — на копии для проверки:

```bash
cd backend
cp data/app.db /tmp/prod_copy.db
WORKSPACE_AUTH_MODE=demo .venv/bin/python -m app.db.migrate --db /tmp/prod_copy.db
WORKSPACE_AUTH_MODE=demo .venv/bin/python -m app.db.migrate --db /tmp/prod_copy.db   # повтор → no-op
```

Артефакт: `<backup-dir>/migration_report.json` (`before/after_null_count`,
`foreign_key_check_ok`, `phase`). Ожидаемо на копии боевой: 249 → 0, ok, повтор
`no-op (already migrated)`. Эталон: `docs/artifacts/stage4b_sql_migration.json`.

## 8. Миграция Chroma (metadata merge без переиндексации)

Источник: `app/db/migrate_chroma.py`. Запускать **после** SQL-фазы (источник
ws — SQL). Отчёт содержит `already_had_ws / orphan_chunks / skipped_no_doc_id`.

```bash
cd backend
cp -R data/chroma /tmp/chroma_copy
WORKSPACE_AUTH_MODE=demo .venv/bin/python -m app.db.migrate_chroma \
  --chroma-dir /tmp/chroma_copy --db /tmp/prod_copy.db
```

Артефакт: `<backup-dir>/chroma_migration_report.json`. Ожидаемо: missing → 0,
`phase: converged`; повтор — `updated: 0`. Эталон:
`docs/artifacts/stage4b_chroma_migration.json`; разбор 39/40 —
`docs/artifacts/stage4b_chroma_migration.md`.

## 9. Ручная двух-workspace проверка (живой сервер)

Сервер из §2, затем (WS_A=ws_a, WS_B=ws_b):

```bash
# upload в ws_a и ws_b (docx с уникальным фактом "Омега 77777" в ws_b)
curl -s -X POST localhost:8000/api/documents -H "X-Workspace: ws_a" \
  -F "file=@samples/User_Guide.pdf;type=application/pdf"            # → 201
curl -s -X POST localhost:8000/api/documents -H "X-Workspace: ws_b" \
  -F "file=@/tmp/ws_b_doc.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document"  # → 201

# изоляция списков и доступа
curl -s -H "X-Workspace: ws_a" localhost:8000/api/documents          # только свои
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Workspace: ws_b" \
  localhost:8000/api/documents/<DOC_ID_A>                            # → 404 (и /file, и DELETE)

# retrieval-изоляция
curl -s -H "X-Workspace: ws_a" "localhost:8000/api/search?q=User+Guide"   # только чанки ws_a
curl -s -H "X-Workspace: ws_b" "localhost:8000/api/search?q=User+Guide"   # только чанки ws_b

# негативный контроль (LLM): ws_a спрашивает про факт ws_b — «нет информации»
curl -s -N -X POST localhost:8000/api/chat -H "X-Workspace: ws_a" \
  -H "Content-Type: application/json" \
  -d '{"message":"Сколько стоит тариф Омега?","model":"zai:glm-5.3-flash"}'
# позитивный контроль: ws_b — цитирует «77 777 руб/мес [1]»
curl -s -N -X POST localhost:8000/api/chat -H "X-Workspace: ws_b" \
  -H "Content-Type: application/json" \
  -d '{"message":"Сколько стоит тариф Омега?","model":"zai:glm-5.3-flash"}'
```

Результат фиксировался вручную (см. `docs/migration-plan.md` §10.1 и
`docs/artifacts/stage4b_summary.md`); автоматический аналог негативного
контроля — `tests/test_chroma_isolation.py::TestChatContextScoped`.
