# STAGE 4B PLAN — Workspace Isolation (Draft v1.1)

Статус: **план на согласование, реализация не начата**. v1.1 — по итогам
архитектурного ревью (auth mode, migration lifecycle, scope provenance,
migration regression tests, scope decisions). Production-код не менялся.
Основание: инспекция кода на коммите `e13d98f` (Stage 4A включён).

---

## 1. Executive summary

Проект — однопользовательское demo: workspace/user scope отсутствует на всех
слоях (SQL-модели, HTTP-роуты, Chroma metadata, retrieval, agent tools, файлы,
история). План вводит минимальную изоляцию: доверенный workspace identity
(`WORKSPACE_AUTH_MODE=strict|demo`, token → `workspace_id` из backend-dependency),
сквозной `workspace_id` через SQLite/Chroma/файлы, обязательный scope-фильтр на
каждом пути чтения/записи и **выделенную** idempotent-команду миграции
(`migrate`) с backup, lock, report и refuse-to-serve при несовместимом state.
Демо-данные мигрируют в workspace `default` без потерь.

## 2. Current state — подтверждено кодом (коммит `e13d98f`)

| Факт | Доказательство |
|---|---|
| Модели без owner-полей | `app/db/models.py`: `Document`, `Conversation`, `Message` |
| Роуты без auth (`Depends(get_db)` — единственная зависимость) | `api/routes/*.py` |
| `list_conversations` — все диалоги базы | `conversations.py:27-29` |
| Feedback берёт Message по id без проверки родителя | `conversations.py:61-71` |
| Chroma: одна коллекция, metadata чанка без workspace | `core/vectorstore.py`, `add_document_chunks` |
| `query()` — фильтры только category/document_ids от клиента | `vectorstore.py:query()` |
| `delete_document(doc_id)` без scope | `vectorstore.py` |
| Agent tools без scope | `agent_tools.py:50-53` (list), `:72-77` (search) |
| Файлы `uploads/{doc_id}{ext}`, doc_id — серверный uuid | `api/routes/documents.py` |
| Frontend: голые fetch без заголовков | `frontend/src/lib/api.ts` |
| Механизм SQLite-колонок уже есть | `db/session.py:_ensure_sqlite_column` |
| JSON-лог чата (request_id/usage/status) уже есть | `chat.py:_log_chat_request` (Stage 4A) |
| Chroma 0.5.23 `update(ids, metadatas)` **мержит** metadata — существующие ключи сохраняются | фактический прогон в этой сессии (EphemeralClient, см. §9.3) |
| Chroma `where` по отсутствующему полю не матчит чанк | стандартная семантика where; **подтвердить integration-тестом при реализации** (тест M-7) |

## 3. Proposed architecture

```
Frontend ── fetch(+X-Workspace-Key) ── FastAPI
                                        │ get_workspace (dependency, trusted)
                                        │   WORKSPACE_AUTH_MODE=strict|demo
                                        │   strict: header → {token: ws} из env
                                        │   demo:   ws="default" без токена
                                        │ → WorkspaceContext(ws_id, request_id)
            ┌───────────────────────────┴──────────────────────┐
      SQLite: .where(Model.workspace_id == ws_id) — всегда
      Chroma: add/query/delete — where={"workspace_id": ws_id} — всегда
      Files:  uploads/{ws_id}/{doc_id}{ext}
      LLM Provider Protocol + usage wrapper (без изменений)
```

Принципы:
1. `workspace_id` всегда из trusted dependency — не из body/query/заголовков.
2. Изоляция enforced в сигнатурах core-функций: `workspace_id` — обязательный
   параметр без default (пропуск = TypeError при старте тестов, не global search).
3. `WORKSPACE_AUTH_MODE=strict` — режим по умолчанию; demo-режим — осознанный
   выбор окружения, а не умолчание.

## 4. Workspace identity / auth flow

- **Workspace-scoped API key, не user auth.** Токен идентифицирует workspace,
  а не пользователя: без сессий, ролей, профилей. В документации и ошибках
  API — формулировка «workspace key».
- **Режимы** (`WORKSPACE_AUTH_MODE` в settings):
  - `strict` (по умолчанию): env `WORKSPACE_TOKENS` (`token=ws,token=ws`) **обязателен**;
    отсутствует/пуст → **ошибка старта приложения** (fail fast, не «тихое
    отключение авторизации»). Header `X-Workspace-Key` обязателен; неизвестный
    токен → 401.
  - `demo`: workspace `default` без токена — для локального демо и тестов;
    тесты явно ставят `WORKSPACE_AUTH_MODE=demo`.
  - Неизвестное значение режима → ошибка старта (fail fast на опечатку).
- **Frontend получает key**: не через build-env и **не как безопасное
  хранилище секрета**. Workspace key — это ключ уровня workspace (аналог
  read/write API-ключа): для demo он вводится пользователем в настройках UI и
  держится в памяти сессии (sessionStorage для удобства перезагрузки — с явной
  пометкой в UI/доках, что это convenience, а не защита; enforcement —
  полностью на backend). Альтернатива для deployment — reverse-proxy
  инжектирует заголовок (frontend вообще не видит key).
- **Запрет подмены**: `workspace_id` отсутствует во всех DTO/формах/query;
  переданный клиентом — игнорируется; заголовок `X-Workspace-Id` не читается.
- **Путь к полноценной auth**: dependency `get_workspace` — единственная точка
  identity; замена на сессии/OIDC позже = переписать одну функцию.

## 5. Data model changes

| Модель | workspace_id | Индекс/связь |
|---|---|---|
| `Document` | да, `String(64)`, NOT NULL | `ix_documents_workspace` |
| `Conversation` | да, NOT NULL | `ix_conversations_workspace` |
| `Message` | нет — наследуется через Conversation (FK CASCADE) | доступ через JOIN Conversation |
| Chroma metadata | да, в каждом чанке | фильтр where |

- Message: дублирующий workspace_id — риск рассинхрона; доступ к Message
  всегда через JOIN `Conversation.workspace_id`.
- Согласованность: Message создаётся только с workspace родительской
  Conversation; upload/delete — из dependency; agent tools — аргумент.
- **Обязательность SQL-фильтра**: helper `get_scoped(db, Model, id, ws)` (None
  на чужом id → 404) и scoped-select; прямые `db.get` в scope-роутах удаляются.
- **Гарантия отсутствия global fallback**: `rag.retrieve`, `vectorstore.query`,
  `agent_tools.run_tool`, `build_index` получают `workspace_id` обязательным
  positional-параметром (без default) — пропуск невозможно скомпилировать
  незаметно; матрица §10 (тест №12).

## 6. API endpoint changes

| Эндпоинт | Изменение |
|---|---|
| Все /api/* | `ws: WorkspaceContext = Depends(get_workspace)` |
| documents list/categories/get/file/delete | scoped-запросы; чужой id → **404** |
| documents upload/demo | `workspace_id=ws.workspace_id` в запись + metadata чанков; путь `uploads/{ws}/{id}{ext}` |
| conversations list/get/rename/delete | scoped; чужой → 404 |
| messages feedback | `db.get(Message)` → JOIN Conversation + проверка ws → 404 |
| chat | ws в retrieve/context/tools/JSON-лог (новое поле `workspace_id`) |
| search | retrieve с ws |
| models, health | без изменений |

Фронтенд: `frontend/src/lib/api.ts` — одна обёртка fetch добавляет
`X-Workspace-Key`; UI-настройка для ввода key (см. §4). Остальной фронтенд
не меняется.

## 7. Chroma isolation

- `add_document_chunks(..., workspace_id)` → в metadata каждого чанка.
- `query(..., workspace_id)` — обязательный `where={"workspace_id": ws}` (AND
  с category/document_ids).
- `delete_document(document_id, workspace_id)`: ownership проверяется на SQL
  уровне до вызова; Chroma-where — второй барьер.
- **Одна коллекция сохраняется** (ограничений не выявлено; Chroma where —
  нативный; корпуса per-workspace малы).
- **Чанки без workspace_id после миграции**: `where` по отсутствующему полю их
  не возвращает — недоступны, а не глобальны; миграция доводит счётчик до 0
  (integration-тест M-7 подтвердит семантику на фактической версии).
- **Восстановление**: полная пересборка индекса (`build_index`) уже
  workspace-aware после изменений.

## 8. File storage isolation

- `uploads/{workspace_id}/{document_id}{ext}`; ws валидируется regex при
  создании контекста — traversal (`../`, `/`, `\`) отсекается до формирования
  пути; `document_id` — серверный uuid.
- Download/delete — только после `get_scoped` authorization (404 на чужой).
- Delete: файл + папка workspace при пустоте.
- Миграция: move существующих файлов в `uploads/default/` (idempotent).

## 9. Migration plan (выделенная команда, не автозапуск)

**Разделение ответственности (устраняет два конкурирующих способа):**
- `init_db()` — **только schema**: `create_all` + `_ensure_sqlite_column`.
  Данные не трогает. Выполняется при старте приложения и в тестах.
- `python -m app.db.migrate` (`backend/app/db/migrate.py`) — **data migration**
  SQL→Chroma→files + integrity report. Запускается вручную/скриптом деплоя.
  НЕ вызывается из `init_db()` и из lifespan.

**Фазы (каждая idempotent, критерий завершения проверяется перед стартом):**

| Фаза | Действие | Idempotency-проверка |
|---|---|---|
| pre | Backup `app.db` и `uploads/` в `backups/<ts>/`; lock-файл (`migration.lock`, эксклюзивно) — конкурентный запуск → отказ с сообщением | lock отсутствует |
| 1 SQL | ensure-колонки workspace_id; `UPDATE … SET workspace_id='default' WHERE NULL` | `COUNT(*) WHERE workspace_id IS NULL = 0` |
| 2 Chroma | батчами (100): чанки без `workspace_id` в metadata → `update(metadatas={"workspace_id": "default"})` — merge подтверждён фактическим прогоном 0.5.23 (существующие ключи не теряются) | `get()`: 0 чанков без workspace_id |
| 3 Files | move `uploads/{id}{ext}` → `uploads/default/{id}{ext}` | нет файлов в корне uploads, соответствующих записям БД |
| post | **Integrity check**: каждая Document/Conversation имеет ws; каждый файл БД существует на ожидаемом пути; в Chroma 0 legacy-чанков; отчёт (JSON + stdout): фазы, счётчики, ошибки | report = "converged" |

**Поведение при частичном завершении:** повторный запуск продолжает с того же
места (все проверки «уже сделано»). Приложение при старте выполняет
**integrity pre-check** (лёгкий: NULL-count в SQL + счётчик legacy-чанков в
Chroma): в `strict`-режиме при несовместимом state — отказ поднимать
обработку запросов (fail fast с инструкцией «запустите migrate»); в `demo` —
предупреждение в лог и продолжение (demo-данные единственные и уже в default
после фаз).

**Порядок фаз SQL → Chroma → files** выбран так, что частичное состояние не
теряет данные: SQL-колонки добавляются до Chroma (метаданные записей существуют),
файлы переезжают последними (БД уже указывает на новые пути; на время окна
между фазами старые пути продолжают работать для read — download до миграции
файлов определяется по старому пути в fallback).

## 10. Security regression test matrix

Базовые 14 сценариев — без изменений (см. Draft v1.0 §10; слои и ожидания):
1 documents list · 2 get по ID (404) · 3 download (404) · 4 delete (404,
chunks/файл B на месте) · 5 chroma chunks · 6 conversations list · 7 message
через JOIN (404) · 8 rename/delete (404) · 9 agent tools scoped · 10
невалидный/отсутствующий token → 401 (strict) · 11 подмена через
body/query/header игнорируется · 12 отсутствие filter → TypeError (сигнатуры) ·
13 demo workspace работает после миграции · 14 Stage 4A suite зелёный.

**+ Миграционные regression тесты (из ревью):**

| # | Сценарий | Слой | Ожидание |
|---|---|---|---|
| M-1 | SQL выполнен, Chroma не тронут | migrate | repeat converges; до Chroma-фазы чанки B недоступны фильтром |
| M-2 | Chroma выполнен, файлы не переезжали | migrate | repeat доезжает до файлов; download A/B раздельно работает |
| M-3 | Файл уже переименован в новый путь | migrate files | пропуск, без ошибки и дубля |
| M-4 | Целевой файл уже существует | migrate files | не перезаписывать; report WARNING; source сохраняется |
| M-5 | Chroma metadata мигрирована частично (1 из 2 чанков) | migrate chroma | повтор доводит все; существующие ключи сохранены |
| M-6 | Re-run миграции сходится к тому же состоянию | migrate | идемпотентность: состояние после 1-го и 2-го запуска идентично |
| M-7 | Chroma update **сохраняет существующие ключи** metadata | интеграция (0.5.23, фактическая версия) | после update присутствуют filename/category + workspace_id; where по ws находит |
| M-8 | Несовместимый state + strict → refuse to serve | startup pre-check | приложение не поднимает роуты; инструкция «run migrate» |
| M-9 | Backup создан до фаз | migrate | файл бэкапа существует и не пуст |
| M-10 | Конкурентный запуск | migrate lock | второй процесс отказывается стартовать |

## 11. Ожидаемый список изменённых файлов

```
backend/app/config.py                       (+WORKSPACE_AUTH_MODE, WORKSPACE_TOKENS,
                                             chat_max_message_chars, agent_query_max_chars)
backend/app/db/models.py                    (+workspace_id, индексы)
backend/app/db/session.py                   (init_db = schema-only; без data-migration)
backend/app/db/migrate.py                   (новый: фазы, lock, backup, report, integrity)
backend/app/api/deps.py                     (новый: WorkspaceContext, get_workspace, get_scoped)
backend/app/api/routes/*.py                 (+Depends(get_workspace), scoped, message-length limit)
backend/app/core/vectorstore.py             (+workspace_id add/query/delete)
backend/app/core/rag.py                     (+обязательный workspace_id в retrieve; контекст без изменений)
backend/app/core/agent_tools.py             (+ws, лимит args.query)
backend/app/core/agent.py                   (прокидывание ws)
backend/app/api/routes/chat.py              (ws в JSON-лог; max message chars)
frontend/src/lib/api.ts                     (+X-Workspace-Key)
frontend/src/components/...                 (минимальный ввод key в настройках — опционально)
backend/tests/test_workspace_isolation.py   (новый: матрица §10)
backend/tests/test_migration_isolation.py   (новый: M-1…M-10)
backend/tests/test_edge_cases.py, test_api.py (fixtures: WORKSPACE_AUTH_MODE=demo)
```

## 12. Порядок реализации

1. config (auth mode, tokens, message/query лимиты) + deps.py (identity).
2. Модели + `init_db` schema-only.
3. Chroma add/query/delete + M-7 verification-тест.
4. Файлы: путь + auth-проверка download.
5. Роуты scoped (`get_scoped`, 404) + message-length limit.
6. Core: обязательный workspace_id (retrieve/run_tool/agent) + args.query limit.
7. `app/db/migrate.py` + M-1…M-10.
8. Frontend заголовок (+UI key-настройка опционально).
9. Матрица §10 + fixtures demo-mode.
10. Полный suite + обновление saas-readiness-audit.md статусов.

## 13. Риски и mitigation

| Риск | Mitigation |
|---|---|
| Пропуск фильтра в новом запросе → global fallback | обязательные сигнатуры core, тест №12, ревью-чеклист |
| Chroma update стёр бы ключи | фактически проверено: merge (M-7 в suite) |
| Частичная миграция | idempotent-фазы, повтор converge, integrity pre-check + refuse-to-serve (strict) |
| Конкурентная миграция | lock-файл (M-10) |
| Строгий режим ломает существующие окружения | fail fast на старте с понятной инструкцией; CI/тесты явно demo |
| Забытый прямой `db.get` | grep-чеклист ревью; get_scoped-тесты |
| Потеря demo-данных | backup pre-фаза; миграция только move/update — деструктивных операций нет |

## 14. Acceptance criteria (обновлено)

1. Матрица §10 зелёная: 14 базовых + 10 миграционных сценариев.
2. Полный suite ≥174 + новые, без ослаблений; тесты явно ставят
   `WORKSPACE_AUTH_MODE=demo`.
3. `WORKSPACE_AUTH_MODE=strict` без `WORKSPACE_TOKENS` → приложение не
   стартует (ошибка старта, тест).
4. Demo workspace `default` после миграции: документы/история/файлы на месте.
5. `rag.retrieve`/`vectorstore.query`/`run_tool` невозможно вызвать без
   workspace_id (обязательные сигнатуры, тест №12).
6. Миграция: идемпотентна (M-6), создаёт backup (M-9), блокирует конкурентный
   запуск (M-10), refuse-to-serve при несовместимом state (M-8).
7. Лог чата содержит `workspace_id` (из trusted context).
8. Чужой ресурс → 404 (никогда не 403 и не 200); тело ответа не различает
   «не существует» и «чужой».
9. `docs/saas-readiness-audit.md` обновлен статусами Data isolation.

## 15. Out of scope (зафиксировано)

Полноценная регистрация/OAuth/OIDC; роли и приглашения; billing; quotas/тарифы;
usage_log таблица (лог остаётся JSON в logger, схему совместим — добавляется
workspace_id поле); LangGraph/Langfuse/LangSmith; S3/presigned URLs; write-tools
агента; переписывание RAG pipeline; массовый рефакторинг вне isolation;
расширение citation held-out (отдельный Stage 4C — зафиксировано).

## 16. Зафиксированные решения (по ревью v1.1)

| Вопрос | Решение |
|---|---|
| Auth mode | `WORKSPACE_AUTH_MODE=strict\|demo`, default **strict**; strict без WORKSPACE_TOKENS → ошибка старта; тесты явно demo |
| Frontend key | ввод в настройках UI, session-хранение как convenience (не защита); enforcement на backend; для deployment — reverse-proxy инжект заголовка; token = workspace-scoped API key, не user auth |
| Миграция | выделенная команда `python -m app.db.migrate` (backup, lock, report, idempotent, integrity); `init_db()` = schema-only; refuse-to-serve при несовместимом state (strict) |
| Чужой ресурс | **404** |
| Citation held-out | отдельный Stage 4C |
| `chat_max_message_chars` | включить в 4B (default 8000 символов — текущие вопросы демо <500, запас ×16) |
| `args.query` агента | ограничить (default 512 символов — усечение, не ошибка) |
| workspace_id в JSON-лог | включить (из trusted context) |
| usage_log table | не добавлять (после workspace, отдельный этап) |
| LangGraph/Langfuse/LangSmith/OAuth/billing/roles/S3 | не добавлять |
