# Stage 4A — Safety Baseline: отчёт

Дата: 2026-10-28. Минимальные safety и resource-management улучшения без
изменения публичного контракта API и без SaaS-функциональности
(без auth/workspace_id/LangGraph/Langfuse — по условиям этапа).

## 1. Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/config.py` | 3 новых настройки: `chat_top_k_max=20`, `max_upload_mb=50`, `chat_context_token_budget=3000` |
| `app/schemas/dto.py` | `ChatRequest.top_k: Field(ge=1)` — 422 на 0/отрицательные |
| `app/api/routes/chat.py` | `_effective_top_k()` (server clamp), замер `retrieval_ms`, JSON-лог `_log_chat_request` (request_id, retrieval/llm/total ms, usage, status), контекстный бюджет |
| `app/api/routes/documents.py` | Лимит размера: pre-check по `file.size` (413 до чтения) + потоковая проверка при записи (413, файл и запись удаляются) |
| `app/core/rag.py` | `build_context(hits, max_tokens)` — целые чанки сверх бюджета отбрасываются (минимум 1); `build_system_prompt(…, max_tokens)` |
| `app/core/vectorstore.py` | `Settings(anonymized_telemetry=False)` — поддерживаемый механизм ChromaDB |
| `app/llm/providers.py` | OpenAI/Zai: `stream_options.include_usage` + защита пустых `choices` + `last_usage`; Ollama: `eval_count` из done-чанка; Anthropic: `get_final_message().usage`; `last_usage` — опциональное расширение Protocol |
| `tests/test_safety_baseline.py` | 15 тестов |
| `README.md` | Приведение «latency in logs» в соответствие с реализацией |

## 2. Выбранные лимиты и обоснование

| Лимит | Значение | Обоснование |
|---|---|---|
| `chat_top_k_max` | 20 | Продовый default 5, векторный поиск UI шлёт 10 (`SearchView.tsx:37`); 20 = запас для больших корпусов и совпадает с `retrieval_candidates` (пул до rerank). Значения выше не дают полезной выдачи, но раздувают промпт |
| `max_upload_mb` | 50 | Согласовано с содержимым демо-корпуса (User Guide: «файлы до 50 МБ») и покрывает документы типичного HR/KB сценария; проверка дважды: по content-length (отказ до чтения) и по факту записи |
| `chat_context_token_budget` | 3000 токенов | Текущие демо-ответы укладываются в ~2–3k токенов контекста (5 чанков) — поведение не меняется; при top_k у капа или длинных чанках лишние чанки отбрасываются **целиком** (без разреза середины текста), минимум 1 чанк сохраняется |

Валидация: `top_k ≤ 0` и не-int → 422 (pydantic `ge=1`); top_k выше капа →
успешный ответ с clamp'нутым значением (не ошибка — graceful degradation);
oversized upload → **HTTP 413**, файл на диске и запись в БД удаляются.

## 3. Usage/latency logging

Каждый chat request пишет одну JSON-строку в `app.chat` logger (после SSE `done`,
не ломая протокол):

```json
{"event": "chat_request", "request_id": "ab12cd34ef56", "mode": "rag",
 "model": "mock", "provider": "mock", "retrieval_ms": 12.4, "llm_ms": 310.2,
 "total_ms": 322.6, "in_tokens": null, "out_tokens": null,
 "usage_source": "unavailable", "status": "ok", "error_category": null,
 "n_sources": 5, "context_chunks": 5}
```

- `usage_source=provider` — счётчики фактические (OpenAI/Z.ai: include_usage;
  Ollama: eval_count; Anthropic: final message); `unavailable` — провайдер не
  вернул usage (mock), **точная стоимость не утверждается**.
- `status`: ok | llm_error; `error_category` — класс исключения.
- **Не логируется**: текст вопроса, текст ответа, имена документов, ключи
  (покрыто тестами `test_log_without_sensitive_data`,
  `test_log_has_request_id_and_usage_unavailable`).
- Важно: включение `include_usage` вскрыло бы latent-баг — старый код читал
  `chunk.choices[0]` и упал бы на usage-чанке с пустым `choices`; добавлена защита.

## 4. Результаты тестов

- Полный сьют: **174 passed** (было 159, +15 новых).
- Новые тесты: top_k 0/отрицательный/строка → 422; clamp сверху (spy на
  `vectorstore.query`); oversized → 413 + отсутствие остатков; обычная загрузка
  в лимите → 201; бюджет контекста (отбрасывание целых чанков, «минимум 1»);
  лог: request_id/usage_source=unavailable/status/total_ms; отсутствие секретов
  в логах; provider usage используется когда есть; SSE: sources→token…→done
  сохранён; chroma `anonymized_telemetry is False`.

## 5. Известные ограничения

1. `file.size` (pre-check) может отсутствовать у некоторых клиентов (chunked
   upload) — тогда срабатывает только потоковая проверка (файл частично пишется
   на диск до отказа; запись и запись в БД удаляются).
2. usage по-прежнему не пишется в БД сообщений — только в лог; агрегатор per
   workspace отложен до workspace isolation (Stage 3B proposal).
3. Message length (вопрос пользователя) не ограничен на бэкенде — добавлено
   только ограничение retrieval-контекста; лимит вопроса — кандидат в Stage 4B.
4. Латентности замеряются клиентскими часами приложения (single-process) —
   для прод-сравнения провайдеров справедлив только benchmark-контур.
5. `llm_ms` не включает время подготовки заголовков SSE — это генерация+стрим.

## 6. Что остаётся для workspace isolation (по saas-architecture-proposal.md)

`workspace_id` в Document/Conversation/Message + в metadata чанков; auth
workspace-token на /api; scope-фильтры в retrieval/agent tools (обязательный
where); файлы `uploads/{workspace_id}/`; usage_log-таблица на базе лога из
этого этапа (схема лога уже совместима: добавить workspace_id полем).
