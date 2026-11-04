# SaaS Readiness Audit — AI-RAG-Chat

Дата: 2026-10-28. Аудит архитектуры с SaaS-перспективой **без** превращения
проекта в SaaS преждевременно. Каждый пункт проверен по коду; формат:
`Текущее состояние | Риск | Доказательство | Рекомендация | Приоритет`.

Оценка уровней приоритета: **P0** — блокирует любое multi-user использование;
**P1** — нужен до первого внешнего пользователя; **P2** — SaaS-фаза.

## 1. Data isolation

| Пункт | Текущее состояние | Риск | Доказательство в коде | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| user/workspace/tenant scope | Отсутствует полностью: ни модели, ни API, ни retrieval не знают о владельце | P0: любое multi-user развёртывание раскрывает все документы и диалоги всем | `app/db/models.py` — `Document`/`Conversation`/`Message` без owner-полей; `app/main.py` — ни одного auth-зависимого роута | Добавить `workspace_id` в `Document`/`Conversation` + auth-зависимость (`get_current_workspace`), фильтр по scope на каждый эндпоинт | P0 |
| Связь документов с владельцем | Документы глобальные, привязка только к `category` (строка из формы загрузки) | P0: любой клиент видит/удаляет/скачивает любой документ | `api/routes/documents.py:129-147` — `list_documents`/`get_document` без фильтра | `workspace_id` + indexed FK | P0 |
| Retrieval изоляция | Chroma-коллекция одна на всё; `query()` фильтрует только по category/document_ids из запроса клиента | P0: retrieval вернёт фрагменты чужих документов | `core/vectorstore.py:query()` — `where` только по category/document_ids | Метаданные `workspace_id` в каждом чанке при индексации + обязательный `where` в `query()` | P0 |
| Изоляция истории диалогов | `list_conversations` возвращает все диалоги базы; доступ по id без проверки | P0: полный доступ к чужим перепискам | `api/routes/conversations.py:27-37` | `workspace_id` в `Conversation` + фильтр на list/get/patch/delete | P0 |
| Проверка доступа на backend | Отсутствует: API полностью открытое (только CORS-allowlist для localhost) | P0 при deployment вне localhost | `app/main.py:26-32`, все роуты | Auth-слой (минимум — API key/workspace token; сессии/_oidc — по потребности) | P0 |

Итог: проект сейчас — **однопользовательский демо-стенд**. Изоляция отсутствует
на всех уровнях (реляция, вектор, история, HTTP). Это осознанный демо-дизайн
(README: «portfolio demo»), но он должен быть зафиксирован явно.

## 2. Document lifecycle

| Пункт | Текущее состояние | Риск | Доказательство | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Загрузка | POST /api/documents: 201 сразу, ingestion в BackgroundTasks, статусы processing→ready/error | Низкий: чистая асинхронность, статус виден в UI | `api/routes/documents.py:49-82`, `_run_ingestion` со своей DB-сессией | Сохранить как есть | — |
| Удаление | Удаляются все три слоя: chunks в Chroma (`delete_document`), файл на диске (`unlink`), запись в БД; RU/EN-пары демо-пака удаляются вместе (`pair_key`) | Низкий; N+1 get на пару — не существенно | `api/routes/documents.py:169-196`, `core/vectorstore.py:delete_document` (`where={"document_id": …}`) | Сохранить | — |
| Связанные chunks/embeddings при удалении | Да, удаляются атомарно по `document_id` | Орфаны возможны только при падении между Chroma и БД (не транзакционно) | `documents.py:188-195` | Idempotent re-delete / periodic reconcile-скрипт | P2 |
| Обновление/переиндексация | Отсутствует: replace = delete + upload вручную; нет PATCH/POST /reindex | Средний: stale-копии при «обновлении» файла тем же именем (filename не уникален) | нет reindex-роута; `upload_document` создаёт новый `Document` всегда | Добавить replace-эндпоинт (delete+upload в одной транзакции) при появлении реальных пользователей | P1 |
| Повторная загрузка | Демо-пак идемпотентен по filename; обычный upload — дубликат с новым id | Дубликаты засоряют retrieval (двойные цитаты одного источника) | `documents.py:98` (`existing` check только в demo) | Дедупликация по content hash (sha256 при приёме) | P1 |
| Stale data | Файл, удалённый с диска, остаётся записью БД до попытки download (`404 Файл отсутствует`) | Низкий | `documents.py:156-158` | Cleanup-джоба по расписанию | P2 |
| Восстановление после ошибки | `status=error` + `error` text сохраняются; повторная загрузка файла создаёт новый документ; **retry-эндпоинта нет** | Средний: исправленный файл = полная повторная загрузка | `core/ingestion.py:69-74`, `documents.py:49-82` | `POST /{id}/reingest` (пере-парсинг сохранённого файла) | P1 |

## 3. Resource management

| Пункт | Текущее состояние | Риск | Доказательство | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Лимит размера файла | Отсутствует (читается целиком в файл на диске; ограничение только proxy/deploy) | DoS/стоимость: файл любого размера принят и проиндексирован | `documents.py:73-76` (`copyfileobj` без лимита) | Лимит в settings (например 50 МБ) + 413 | P1 |
| Лимит количества документов | Отсутствует | Бесконечный рост индекса | `documents.py` | Квота на workspace (SaaS-фаза; для демо не нужно) | P2 |
| Token/context size | top_k приходит от клиента без кэпа (только `min(n_candidates, count)` внутри); длина контекста не контролируется | Раздувание промпта: top_k=50 → огромный CONTEXT → стоимость/таймаут | `ChatRequest.top_k` (`dto.py:53`), `vectorstore.query` | Серверный cap top_k (например ≤10) и лимит токенов контекста | P1 |
| Timeout | LLM: 180 с (OpenAI-совместимые), 600 с read (Ollama); retrieval без таймаута | Долгие зависания держат SSE | `llm/providers.py:23`, `providers.py:218` | Сохранить; добавить таймаут на retrieval-этап агента | P2 |
| Cancellation | SSE: при разрыве клиента generator отменяется uvicorn'ом; фоновая генерация заголовка (`BackgroundTasks`) продолжается после разрыва | Лишний вызов LLM при закрытой вкладке (списывание токенов) | `chat.py:120-126` (`background.add_task(_generate_title_task)`) | Проверять client-disconnect перед title-задачей; document-ингест продолжать (правильно) | P2 |
| Retry | SDK max_retries=1 (openai/anthropic); своих retry нет | Простые сбои ретраятся SDK'ом; остальное — честный error event | `providers.py:106`, `chat.py:109-111` | Сохранить; retry-политика провайдера в settings | P2 |
| Usage/cost контроль | usage от провайдера приходит в SDK, но **в чате не собирается и не логируется**; стоимость считается только в offline-benchmark | Нет контроля расходов per workspace/запрос | `chat.py` — нет записи usage; сборка есть только в `benchmarks/llm_bench.py` | Логировать usage (model, in/out tokens) на каждый запрос; агрегатор per workspace | P1 |

## 4. Provider abstraction

| Пункт | Текущее состояние | Риск | Доказательство | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Общий интерфейс | `LLMProvider` Protocol (stream, available) + registry с ModelSpec | Низкий: добавление провайдера = один класс + строка в реестре | `llm/base.py`, `llm/registry.py` | Сохранить | — |
| Streaming | Единый AsyncIterator[str] у всех провайдеров, включая mock | — | `providers.py` (все `.stream`) | Сохранить | — |
| Timeout/errors | Таймауты в каждом провайдере; ошибки оборачиваются в SSE error event | Разброс констант (180/600) — ок для демо | `providers.py`, `chat.py:109-111` | Централизовать в settings | P2 |
| Usage metadata | В прод-пути отсутствует (см. §3) | Нет данных для квот/стоимости | `chat.py` | Единый wrapper: stream→(tokens, usage) — уже реализован в benchmark, можно поднять | P1 |
| Бизнес-логика vs LLM API | Отделена: rag/agent работают только через Protocol; ни одного импорта SDK в core | — | `core/rag.py`, `core/agent.py` | Сохранить | — |

## 5. Security and observability

| Пункт | Текущее состояние | Риск | Доказательство | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Prompt injection из документов | Контекст подаётся в system verbatim без санитизации; агент-режим исполняет JSON-инструкции из вывода модели, который мог быть отравлен документом | Средний: документ может заставить агента искать/цитировать произвольное; инструментов с write-эффектами нет (list/search — read-only), прямой exfiltration-канал — финальный ответ пользователю | `core/agent.py:117-171`, `rag.py:10-19` | Помечать контекст как untrusted в промпте; валидировать tool-args (схемы); не добавлять write-tools без auth | P1 |
| Privacy документов | Файлы на диске в открытом виде (`uploads/`), SQLite без шифрования, download без auth | При наружном deployment — полный доступ к файлам | `documents.py:150-166` | Для multi-user: auth (см. §1), файлы вне webroot, presigned/авторизованный download | P0 (вместе с auth) |
| Logging без утечки секретов | Ключи не логируются (ни один лог-вызов не печатает settings/headers); chromadb-telemetry ошибки печатаются в stderr | Низкий; телеметрия chromadb шумит | инспекция логов запуска uvicorn | Отключить chromadb telemetry (env/anonymous telemetry=false) | P2 |
| Latency/observability | Feedback 👍/👎 и agent_steps сохраняются в БД; **latency в логах отсутствует** (README утверждает «latency in logs» — расхождение README↔код) | Слепая зона: прод-латентность не наблюдаема | инспекция `chat.py` — нет logging | Добавить structlog/print latency per request (model, retrieval_ms, llm_ms) — дешёво и закрывает расхождение | P1 |
| Opt-in observability | Нет (Langfuse/LangSmith не интегрированы — по решению Stage 3A/3B) | — | — | См. docs/orchestration-decision.md и proposal | P2 |

## 6. Что уже сделано хорошо (не ломать)

- Чистая слоистая архитектура (`api/core/llm/db/parsers/schemas`) — бизнес-логика
  изолирована от FastAPI и LLM SDK.
- Provider Protocol + registry + mock — SaaS-ready по форме.
- Async ingestion с фоновой задачей и статусами.
- Полный lifecycle удаления трёх слоёв данных.
- Изолированные eval-хранилища (`data/eval`, `data/test`) — рабочие данные не
  загрязняются тестами.

## 7. Честные ограничения аудита

- Frontend рассмотрен на уровне вызовов API (`lib/api.ts` не инспектировался
  построчно) — риск XSS в рендере markdown-ответов не проверен.
- Deployment-контур (Dockerfile, nginx-шаблон, Render) не аудировался на
  заголовки безопасности (CSP, X-Frame-Options).
- Нагрузочные характеристики SQLite под конкурентной записью не измерялись.
