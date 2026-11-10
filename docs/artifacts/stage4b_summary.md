# Stage 4B — Workspace Isolation: сводка (для интервью)

Одна страница фактов; обоснование и ход рассуждений — в
[docs/report-mws-ai.md](../report-mws-ai.md) §7.5 и
[docs/migration-plan.md](../migration-plan.md). Все цифры — из JSON-артефактов.

## 1. Что изолировано

| Слой | Механизм |
|---|---|
| SQL | `workspace_id`: nullable → backfill `'default'` → table rebuild → `NOT NULL DEFAULT 'default'` (модель и DDL синхронны) |
| API | `Depends(get_workspace)` (trusted backend context; demo `X-Workspace` / strict `X-Workspace-Key`) + scoped-запросы; чужой ресурс → **404** (не 403 — не раскрывает существование) |
| Chroma | `workspace_id` в metadata каждого чанка (**merge** через `update`, без переиндексации векторов) + обязательный `where` в query/delete; вызов без ws → ValueError |

## 2. Миграция боевой базы (2026-11-09)

| Фаза | Результат | Время |
|---|---|---|
| SQL (`app/db/migrate.py`) | 249 NULL → 0 (18 documents + 231 conversations → `'default'`), `foreign_key_check: ok` | ~24 ms |
| Chroma (`app/db/migrate_chroma.py`) | 39 missing → 0 из **40**; 1 already_had_ws (`agent-doc.docx`, ws=`ws-a` — загружен после Step 3, до миграции), orphan_chunks 0 | ~0.6 s |
| Backup | `backend/backups/prod_20261109T114847Z_d818d5/` — app.db (integrity_check ok) + chroma/ (размер сверен) + uploads/, 7.8 MB | — |
| Идемпотентность | повтор обоих migrate — `no-op (already migrated)` / `converged` | — |

## 3. Ручная двух-workspace проверка (живой сервер, GLM-5.3-flash)

| Сценарий | Результат |
|---|---|
| upload ws_a (User_Guide.pdf) / ws_b (факт «Омега 77777») | 201 / 201 |
| list ws_a / ws_b | только свои документы |
| get / file / delete документа ws_a из ws_b | **404 / 404 / 404**, документ жив |
| /api/search ws_a «User Guide» / тот же запрос из ws_b | только чанки своего workspace |
| **chat ws_a** «Сколько стоит тариф Омега?» (негативный контроль) | «нет информации о тарифе Омега» — **факт ws_b не утёк** |
| **chat ws_b** (позитивный контроль) | «тариф Омега стоит 77 777 руб/мес [1]» — свой факт процитирован |
| без header | workspace `default` |

## 4. Артефакты и тесты

- JSON-отчёты миграции: `backend/backups/prod_20261109T114847Z_d818d5/migration_report.json`
  (+ `chroma_migration_report.json` там же); эталонные копии —
  [stage4b_sql_migration.json](stage4b_sql_migration.json),
  [stage4b_chroma_migration.json](stage4b_chroma_migration.json);
  разбор 39/40 — [stage4b_chroma_migration.md](stage4b_chroma_migration.md).
- Тесты: `backend/tests/test_workspace_isolation.py` (14 cross-workspace
  сценариев), `backend/tests/test_chroma_isolation.py` (retrieval-изоляция,
  включая интеграционный «chat ws_a не содержит факт ws_b»). Полный suite —
  260 passed.
- Воспроизведение всех цифр: [docs/reproduce.md](../reproduce.md)
  (команда → ожидаемый артефакт → где смотреть).

## 5. Ограничения

- Demo-режим `X-Workspace` — **labeling, не auth**: заголовок подменяем
  клиентом; enforcement — в strict-режиме (`WORKSPACE_TOKENS`, workspace-scoped
  API key, fail fast на старте).
- Rate limiting, audit log, production auth (сессии/OIDC) — future work
  (см. report §7.5).
