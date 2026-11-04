# SaaS Architecture Proposal — минимальный целевой контур

Дата: 2026-10-28. Принцип: **минимальные изменения, открывающие путь к SaaS**,
без billing/subscriptions/Kubernetes/микросервисов — они не включаются, потому
что для них нет ни пользователей, ни операционной потребности; каждое из них
добавляется позже без ломки этого контура.

## 1. Целевая архитектура (минимум)

```
Frontend (React) ── /api (SSE+REST) ── FastAPI
                                        │  Auth: workspace token → workspace_id
                                        │  Routers: documents / chat / conversations / models / search
                                        │  Scope-фильтр на каждый запрос (workspace_id)
                    ┌───────────────────┴────────────────────┐
              SQLite (metadata)                     Chroma (chunks)
        conversations, messages, documents    metadata: + workspace_id в каждом чанке
        (+ workspace_id, + usage_log)         query(): where={"workspace_id": …} всегда
                    │
              uploads/{workspace_id}/{doc_id}.{ext}   (файлы вне webroot)
                    │
        LLM Provider Protocol (без изменений) + usage wrapper → usage_log
```

Ключевое свойство: **workspace_id как сквозной идентификатор изоляции** —
один столбец в трёх таблицах, одно поле в metadata чанка, одна auth-зависимость.
Дешёвая замена полноценного users/tenants, оставляющая место для них позже
(workspace → user(s) — следующая итерация).

## 2. API boundaries

- Все существующие эндпоинты сохраняют контракт фронтенда; добавляется только
  заголовок/token workspace (например `X-Workspace-Key`).
- Retrieval и agent tools получают `workspace_id` как обязательный параметр
  (не опциональный!) — компилятор/тесты ловят пропуски.
- Download файлов — только через авторизованный эндпоинт (не статику).
- Слои не меняются: auth живёт в api/, scope — в параметрах core-функций.

## 3. Разбивка рекомендаций

### Required now (не зависит от SaaS, закрывает измеренные проблемы)

| # | Изменение | Обоснование (из Stage 2/3) |
|---|---|---|
| 1 | Серверный cap `top_k` и лимит токенов контекста | `top_k` неконтролируем клиентом |
| 2 | Лимит размера загружаемого файла (settings, 413) | приём файла любого размера |
| 3 | Usage-логирование per request (model, in/out tokens, retrieval_ms, llm_ms) | закрывает и расхождение README «latency in logs», и основу для квот |
| 4 | Отключение chromadb telemetry | шум в логах |
| 5 | Datasheet-фикс README «latency in logs» после п.3 | честность документации |

### Required before multi-user deployment

| # | Изменение | Почему именно так |
|---|---|---|
| 1 | `workspace_id` в Document/Conversation/Message + в metadata чанков | минимальная изоляция (см. §1) |
| 2 | Auth-зависимость (workspace token) на все /api роуты | backend-проверка доступа |
| 3 | Scope-фильтр в retrieval/agent tools (обязательный where) | изоляция вектора |
| 4 | Файлы в `uploads/{workspace_id}/`, download через auth | privacy документов |
| 5 | Replace/reingest эндпоинт + дедупликация по content hash | lifecycle без stale-дубликатов |
| 6 | Prompt-injection гигиена: untrusted-маркировка контекста, схемы tool-args | агент работает с недоверенным текстом |

### Future SaaS features (не реализовывать без пользователей)

- users/roles (admin/member), приглашения; per-workspace квоты и cost-дашборд
  (на базе usage_log);
- Postgres вместо SQLite (при реальной конкурентной записи);
- Langfuse/LangSmith opt-in tracing прод-трафика (решение Stage 3: отложено);
- LangGraph при write-tools/multi-агентах (см. orchestration-decision.md);
- multi-tenant векторные коллекции или per-tenant namespaces — только если
  shared-коллекция с where-фильтром упрётся в производительность.

## 4. Privacy-aware observability (принципы на будущее)

- Opt-in через env; без credentials приложение полнофункционально.
- Один trace на запрос; observations: retrieval (запрос, top_k, latency),
  context assembly (число чанков, суммарные токены — НЕ текст), LLM call
  (model, параметры, usage, ошибки), citation validation (результаты проверок).
- По умолчанию **не отправлять**: текст документов, фрагменты контекста,
  вопросы пользователей, ключи. Только метаданные и метрики; полный текст —
  только при явной `TRACING_INCLUDE_CONTENT=1`.

## Part 4. Citation prompt decision (V2 → production?)

**Данных для полного переноса недостаточно.** Что известно: dev coverage
17%→42%, held-out 38%→50% при неизменном correctness/refusal и precision 1.0 —
но разница держится на 3 dev-ответах и 1 held-out-ответе.

План подтверждения:

1. **Расширить held-out минимум до 20 answer cases** (+6–8 negative):
   по 3–4 вопроса на каждый документ/язык, категории fact/numeric/paraphrase/
   cross-lingual; схема v2 (supported/abstention/pages); составление — до
   любого прогона нового prompt, фиксация hash набора в артефакте.
2. **Не использовать held-out для tuning**: все вариации промпта — только на
   dev; held-out гоняется один раз для V0 и один раз для выбранного кандидата
   (как в Stage 3A), после чего набор «расходуется» и расширяется заново.
3. **Критерии acceptance** (все обязательны):
   - correctness held-out: candidate ≥ baseline − 1 ответ (допуск на 1 краевой
     случай; при большем падении — reject);
   - refusal: без выдуманных фактов, как baseline;
   - citation coverage: candidate > baseline (строго);
   - citation precision: не ниже baseline − 0.05 (формальные цитаты недопустимы);
   - отсутствие повторов/обрезаний сверх baseline.
4. **Ограничения выборки — честно**: даже 20 вопросов не дают статистической
   надёжности: 95%-ный доверительный интервал для доли при n=20 — шире ±20 п.п.
   (правило трёх сигм: 0 дефектов из 20 → верхняя граница ~14%). 20 вопросов —
   это **sanity-check направления**, а не доказательство. Решение о переносе
   принимается по совокупности: направление на dev + подтверждение на held-out +
   отсутствие деградации ни по одной метрике; окончательная валидация — только
   на реальном использовании (usage_log + feedback 👍/👎 после переноса).

Отдельно: переносить V2 следует **только для локального провайдера**
(Ollama/llama.cpp ветка) — облачным моделям (GLM-5.3-flash: coverage 100%)
дополнительные требования не нужны и добавляют ~100 токенов overhead.

## 5. Следующий конкретный implementation stage

Stage 4 (предложение): «Isolation foundation» — Required-now пункты (top_k cap,
file size limit, usage logging) + workspace-изоляция (P0-блок: workspace_id в
моделях/чанках/auth-зависимость/scope-фильтры) с регрессионными тестами
изоляции (запрос без scope → пусто; чужой id → 404) и параллельным расширением
held-out до 20 вопросов для citation decision.
