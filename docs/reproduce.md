# Reproduce — how to reproduce the project's measurements

A single command cheat sheet. Format: command → expected artifact → where to
look. Full methodology is in [docs/benchmark.md](benchmark.md); this file is
commands only. All eval/benchmark commands run from `backend/` with
`WORKSPACE_AUTH_MODE=demo` (CLI tools operate in the `default` workspace; the
app's strict mode requires `WORKSPACE_TOKENS` and fails fast without it — that
is by design, not an error).

## 1. Installation

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # application
pip install -r requirements-dev.txt      # tests (pytest, reportlab)
cp .env.example .env                     # keys optional (mock mode works without them)
```

`.env` (all optional unless strict): `ZAI_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY` — LLM providers; `WORKSPACE_AUTH_MODE=strict|demo`
(default strict; strict requires `WORKSPACE_TOKENS=token=ws,…`);
`WORKSPACE_AUTH_MODE=demo` — a single `default` workspace without a token
(local development and the CLI tools below).

## 2. Running the app

```bash
cd backend
WORKSPACE_AUTH_MODE=demo .venv/bin/uvicorn app.main:app --reload --port 8000
```

Check: `curl http://localhost:8000/api/health` → `{"status": "ok", …}`.
Demo documents: `curl -X POST http://localhost:8000/api/documents/demo`.

## 3. Tests

```bash
cd backend
.venv/bin/pytest -q                # full suite (260; ~15–20 s, no network)
```

Result: `260 passed`. No live-API tests in the suite (the `live` marker in
pytest.ini is reserved and excluded by default: `-m 'not live'`).

## 4. Retrieval evaluation (dense / bm25 / hybrid)

Source: `benchmarks/retrieval_eval.py`; held-out set — 47 queries
(`eval/golden_retrieval.json`).

```bash
cd backend
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/retrieval_eval.py --strategy all --repeats 3
```

Artifact: `results/<ts>_retrieval_all.json` + `.csv` (raw per-query rows,
git commit, command, dataset sha256, dependency versions).
Expected metrics (bit-stable across runs): hybrid **R@1 0.8723, R@3 0.9787,
MRR@5 0.9255, nDCG@5 0.9395**; dense R@1 0.5319; bm25 R@1 0.8723.

## 5. Reranker evaluation (rejected alternative, ADR-002)

Source: `benchmarks/reranker_eval.py`; CPU ONNX ~1 GB (first run downloads
the model), candidates hybrid top-20 → rerank → top-5.

```bash
cd backend
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/reranker_eval.py
```

Artifact: `results/<ts>_reranker.json` (+ csv). Expected: Recall@1 ≈ 0.617,
rerank p50 ≈ 6–7 s (the degradation is the reason for rejection, see ADR-002).

### If your numbers differ from the expected (§4–§5)

- Check the held-out set sha256 in your artifact (`eval/golden_retrieval.json`) —
  does it match `env.golden_set_sha256` in the artifact?
- fastembed and embedding-model versions — the `env.dependencies` field.
- Parameters: RRF k=60, top-k, strategy — the `command` field in the artifact.
- If everything matches but the metrics differ — compare against the reference
  artifacts committed in `results/`.
- Do not "tune" the numbers: a discrepancy is either the environment or a real
  bug; in both cases record it and investigate — never edit the metrics.

## 6. Answer evaluation (live GLM — paid API)

Source: `benchmarks/answer_eval.py`; requires `ZAI_API_KEY` in `backend/.env`.
Cost: ~17 answer+judge requests per run (pennies, but not zero).

```bash
cd backend
# held-out v2 (8 answer + 3 negative): GLM-5.3-flash answers + GLM-4.5-flash judge
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/answer_eval.py \
  --model zai:glm-5.3-flash --judge zai:glm-4.5-flash --golden golden_answers_v2.json
# free re-evaluation of saved answers (no LLM):
WORKSPACE_AUTH_MODE=demo .venv/bin/python benchmarks/answer_eval.py \
  --answers-from ../results/<file>_local_answers_*.json --golden golden_answers_v2.json --no-judge
```

Artifact: `results/<ts>_answer_eval_*.json` (+ csv). Expected (held-out v2,
GLM-5.3-flash): correctness 1.0, citations 8/8, refusal 3/3 — **small sample
(8+3): a direction, not proof**.

## 7. SQL migration (workspace backfill + NOT NULL)

Source: `app/db/migrate.py`. Backup + lock + JSON report + no-op on rerun.
The production DB is already migrated — use a copy to verify:

```bash
cd backend
cp data/app.db /tmp/prod_copy.db
WORKSPACE_AUTH_MODE=demo .venv/bin/python -m app.db.migrate --db /tmp/prod_copy.db
WORKSPACE_AUTH_MODE=demo .venv/bin/python -m app.db.migrate --db /tmp/prod_copy.db   # rerun → no-op
```

Artifact: `<backup-dir>/migration_report.json` (`before/after_null_count`,
`foreign_key_check_ok`, `phase`). Expected on a prod copy: 249 → 0, ok, rerun
`no-op (already migrated)`. Reference: `docs/artifacts/stage4b_sql_migration.json`.

## 8. Chroma migration (metadata merge, no re-embedding)

Source: `app/db/migrate_chroma.py`. Run **after** the SQL phase (the ws source
is SQL). The report includes `already_had_ws / orphan_chunks / skipped_no_doc_id`.

```bash
cd backend
cp -R data/chroma /tmp/chroma_copy
WORKSPACE_AUTH_MODE=demo .venv/bin/python -m app.db.migrate_chroma \
  --chroma-dir /tmp/chroma_copy --db /tmp/prod_copy.db
```

Artifact: `<backup-dir>/chroma_migration_report.json`. Expected: missing → 0,
`phase: converged`; rerun — `updated: 0`. Reference:
`docs/artifacts/stage4b_chroma_migration.json`; the 39/40 breakdown —
`docs/artifacts/stage4b_chroma_migration.md`.

## 9. Manual two-workspace check (live server)

Server from §2, then (WS_A=ws_a, WS_B=ws_b):

```bash
# upload to ws_a and ws_b (a docx with the unique fact "Omega 77777" in ws_b)
curl -s -X POST localhost:8000/api/documents -H "X-Workspace: ws_a" \
  -F "file=@samples/User_Guide.pdf;type=application/pdf"            # → 201
curl -s -X POST localhost:8000/api/documents -H "X-Workspace: ws_b" \
  -F "file=@/tmp/ws_b_doc.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document"  # → 201

# list and access isolation
curl -s -H "X-Workspace: ws_a" localhost:8000/api/documents          # own docs only
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Workspace: ws_b" \
  localhost:8000/api/documents/<DOC_ID_A>                            # → 404 (same for /file and DELETE)

# retrieval isolation
curl -s -H "X-Workspace: ws_a" "localhost:8000/api/search?q=User+Guide"   # ws_a chunks only
curl -s -H "X-Workspace: ws_b" "localhost:8000/api/search?q=User+Guide"   # ws_b chunks only

# negative control (LLM): ws_a asks about a ws_b fact → "no information"
curl -s -N -X POST localhost:8000/api/chat -H "X-Workspace: ws_a" \
  -H "Content-Type: application/json" \
  -d '{"message":"Сколько стоит тариф Омега?","model":"zai:glm-5.3-flash"}'
# positive control: ws_b → cites "77 777 руб/мес [1]"
curl -s -N -X POST localhost:8000/api/chat -H "X-Workspace: ws_b" \
  -H "Content-Type: application/json" \
  -d '{"message":"Сколько стоит тариф Омега?","model":"zai:glm-5.3-flash"}'
```

Results were recorded manually (see `docs/migration-plan.md` §10.1 and
`docs/artifacts/stage4b_summary.md`); the automated counterpart of the
negative control — `tests/test_chroma_isolation.py::TestChatContextScoped`.

---

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
