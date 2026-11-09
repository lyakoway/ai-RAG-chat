# Migration Plan — workspace_id backfill, rebuild и gate до API isolation

Статус: **Stage 4B COMPLETE** — изоляция SQL + API + Chroma реализована,
**боевая миграция выполнена** 2026-11-09 (backup `backups/prod_20261109T114847Z_d818d5/`,
отчёты в `migration_report.json` и `chroma_migration_report.json` внутри).

Факты боевой миграции:
- SQL: 249 NULL → 0 (`documents` 18 + `conversations` 231 → 'default'),
  foreign_key_check ok, ~1.1 s;
- Chroma: 40 чанков, 39 missing → 0 updated (metadata merge, без переиндексации),
  converged, ~0.6 s;
- оба migrate повторно: **no-op / converged** (идемпотентность на боевой базе);
- общий backup: app.db (integrity_check ok) + chroma/ (размер совпадает) +
  uploads/; retention — хранить ≥ N дней (N определяется владельцем);
- ручная двух-workspace проверка на живом сервере — пройдена (см. §10.1 ниже).

### §10.1 Ручная двух-workspace проверка (живой сервер, 2026-11-09)

| # | Сценарий | Результат |
|---|---|---|
| 1 | upload ws_a (User_Guide.pdf), upload ws_b (факт «Омега 77777») | 201/201 |
| 2 | list ws_a | только User_Guide.pdf (2 файла) |
| 3 | list ws_b | только ws_b_doc.docx |
| 4 | GET документа ws_a с ws_b | **404** |
| 5 | GET файла ws_a с ws_b | **404** |
| 6 | DELETE документа ws_a с ws_b | **404**, документ жив |
| 7 | /api/search ws_a «User Guide» | только User_Guide.pdf |
| 8 | /api/search ws_b тот же запрос | только ws_b_doc.docx (top-k ближайшие своего ws; нерелевантный свой текст — качество retrieval, не утечка) |
| 9 | chat ws_a «Сколько стоит тариф Омега?» (GLM-5.3-flash) | «нет информации о тарифе Омега» — **77777 не утек** |
| 10 | chat ws_b тот же вопрос (позитивный контроль) | «тариф Омега стоит 77 777 руб/мес [1]» — свой факт процитирован |
| 11 | без header | workspace `default`, свои 18 документов |
Основание: фактическая верификация кода на коммите `93fdaf1` + Stage 4A.

## 1. Текущее состояние (факты этапа 1)

| Факт | Доказательство |
|---|---|
| `Document.workspace_id`, `Conversation.workspace_id` — `String(64)`, `nullable=True`, index | `app/db/models.py` (Stage 4B Step 2) |
| После migrate фазы 1 требуется **синхронное** переключение `nullable=False` в models.py | TODO добавлен в `models.py` (блок Conversation.workspace_id) |
| `migrate.py` **не существует** | `ls app/db/migrate.py` → No such file |
| FK не enforced в рантайме: `PRAGMA foreign_keys = 0` по умолчанию | фактический замер через SQLAlchemy (результат 0) |
| `Message.conversation_id → Conversation.id, ondelete="CASCADE"` объявлен в модели, но при foreign_keys=0 удаление Conversation на SQL-уровне оставит orphan-строки; ORM-каскад (`cascade="all, delete-orphan"`) удаляет messages только через сессию | `models.py:64-77`, `conversations.py:52-57` |
| Chroma metadata каждого чанка содержит `document_id` (и filename/category/page/label/chunk_index) | `core/vectorstore.py:add_document_chunks` |
| Chroma 0.5.23 `update(ids, metadatas)` мержит metadata, существующие ключи сохраняются | фактический прогон (Stage 4B review) |
| Существующие записи `Document`/`Conversation` имеют `workspace_id = NULL` (переходное состояние Step 2) | Stage 4B Step 2 отчёт; тест `test_init_db_does_not_backfill_workspace` |
| Ингест/создание записей пока без workspace (роуты не подключены) | `documents.py`, `chat.py` — без ws-полей |

### Инвентаризация Message (все места чтения/записи)

| Место | Операция | Категория | Условие |
|---|---|---|---|
| `chat.py:111` | запись user Message по `conv.id` | safe* | `*conv` создан/получен в запросе — на Step 3 conv будет scoped |
| `chat.py:_persist_assistant` | запись assistant Message по `conv_id` | safe* | аналогично |
| `chat.py:117-119` | чтение history `where(Message.conversation_id == conv.id)` | needs-review | фильтр по conversation_id без workspace-проверки; безопасно ТОЛЬКО если conv получен через scoped-запрос (Step 3) |
| `conversations.py:65` — `set_message_feedback` | `db.get(Message, message_id)` напрямую, без связи с Conversation | **unsafe** | доступ к Message любого workspace; Step 3: JOIN с Conversation + проверка ws → 404 |
| `conversations.py` get_conversation / delete (ConversationDetail.messages, cascade) | чтение/удаление через relationship | safe* | при scoped Conversation |
| `models.py:66-69` relationship | ORM-каскад | safe | — |
| `tests/*` | тестовые фикстуры | n/a | — |

Категории: **safe** — уже корректно при scoped parent (Step 3); **needs-review** —
работает, но требует обязательной проверки workspace при Step 3; **unsafe** —
текущий путь допускает cross-workspace доступ.

## 2. Целевое состояние

1. В БД: `documents.workspace_id` и `conversations.workspace_id` — `NOT NULL`,
   без NULL-строк; все существующие записи в workspace `default`.
2. В models.py: `nullable=False` (TODO уже размечен; изменение — в том же
   коммите, что и migrate фаза 1).
3. API фильтрует по workspace (Step 3).
4. Chroma retrieval фильтрует по workspace (Step 4): metadata-миграция
   (`update` merge, без переиндексации векторов) + обязательный `where`.

## 3. Порядок шагов

1. **migrate.py фаза 1**: backup → backfill `NULL→'default'` → table rebuild с
   NOT NULL constraint → integrity check → report. Не трогает API.
2. **models.py nullable=False** — синхронно в том же коммите (TODO размечен).
3. **Step 3: API isolation** — `Depends(get_workspace)` на роуты, scoped-запросы,
   закрытие unsafe-места feedback, JOIN для history.
4. **Step 4: Chroma isolation** — metadata update всех чанков + обязательный
   where в query/delete; затем Step 3 API уже не может получить чужие чанки.

## 4. Gate-условие

**Step 3 (API isolation) НЕ начинается**, пока не выполнены ВСЕ:

- [x] `app/db/migrate.py` реализован и фаза 1 выполнена на копии рабочей базы
      (249 NULL → 0, foreign_key_check ok, повторный запуск no-op);
- [x] models.py переключён на `nullable=False` + `default/server_default`
      (тесты TestModelMigrationSync доказывают синхронность DDL и модели);
- [x] инвентаризация Message закрыта: unsafe `conversations.py:65` помечен
      для scoped-замены в Step 3 (обязательный пункт Step 3 checklist);
- [x] план Chroma-изоляции определён (metadata update merge без
      переиндексации — подтверждено фактическим прогоном 0.5.23; тест M-7 —
      при реализации Step 4).

**Gate пройден; Step 3 (API isolation) и Step 4 (Chroma isolation) ВЫПОЛНЕНЫ**
(2026-11-08 / 2026-11-09):
Depends(get_workspace) на documents/chat/conversations/feedback; scoped
list/get/rename/delete/download/upload; unsafe `set_message_feedback` закрыт
(JOIN Conversation); history scoped через JOIN Conversation; agent
list_documents scoped; chat создаёт Conversation с workspace_id явно; JSON-лог
пишет workspace_id. Чужой ресурс → 404 (не 403/401) — подтверждено тестами
(test_workspace_isolation.py, 14 сценариев) и ручной проверкой живого сервера.

Изоляция полная: SQL + API + Chroma. Multi-user deployment требует лишь
замены workspace labeling (X-Workspace в demo) на полноценную auth.

## 5. Rollback

- **Обязательный backup** перед миграцией: копия `app.db` и `uploads/` в
  `backups/<timestamp>/` (фаза pre, fail при невозможности создать).
- Rollback данных: восстановление `app.db` из backup (SQL-данные + схема до
  NOT NULL); Chroma не затрагивается фазой 1; файлы не перемещаются.
- Rollback кода: revert коммита с nullable=False (models.py) + revert migrate.py;
  schema-колонки nullable остаются совместимыми со старым кодом.
- После rollback: повторный запуск миграции возможен (идемпотентные фазы),
  повторный backup создаётся заново.

## 5.1. Статус реализации (2026-11-08)

- **Фаза A** (`app/db/migrate.py`): реализована — backup с integrity check,
  lock, одна транзакция backfill+rebuild, идемпотентность (notnull=1 AND
  NULL=0 AND DEFAULT 'default' → no-op), отчёт JSON, Rollback в docstring.
  Прогнана на копии боевой базы: **249 NULL → 0**, foreign_key_check ok.
- **Фаза B**: models.py `nullable=False, default='default',
  server_default=text("'default'")` — модель и DDL миграции синхронны
  (тесты `TestModelMigrationSync`: ORM без ws → 'default'; прямой SQL INSERT
  без ws → 'default'; ORM NULL → Python-default 'default', raw NULL →
  IntegrityError).
- Если процесс миграции упал, lock-файл `<db>.migration.lock` остаётся;
  удалить вручную после проверки, что процесс миграции не работает.
- ~~Промежуточный риск до Step 4~~ **ЗАКРЫТ (Step 4 выполнен, 2026-11-09)**:
  retrieval изолирован — `vectorstore.query/delete/add` требуют workspace_id
  (отсутствие → ValueError, никакого global fallback), metadata каждого чанка
  содержит workspace_id; миграция `app/db/migrate_chroma.py` заполнила
  workspace_id всем существующим чанкам (metadata merge без пересчёта
  векторов; прогон на копии: 36→0 missing, converged, повтор no-op).
  Integration-тесты: /api/search и RAG-контекст ws_a не возвращают и не
  цитируют чанки ws_b (test_chroma_isolation.py).

## 6. Ограничения

- **SQLite ALTER TABLE**: `ADD COLUMN … NOT NULL` без DEFAULT отклоняется;
  поэтому фаза 1 — backfill → **table rebuild** (create new table → INSERT
  SELECT → drop old → rename) → только после rebuild возможен NOT NULL.
- **FK на время rebuild**: `PRAGMA foreign_keys=OFF` до rebuild (текущее
  состояние и так OFF — зафиксировано), `ON` + `PRAGMA foreign_key_check`
  после. При rebuild `conversations` существующие `messages` сохраняются
  (копируются/остаются в своей таблице; ссылка по conversation_id не меняется
  — id сохраняются).
- **Нет online-миграции**: на время миграции приложение не должно
  обслуживать запросы (для demo — остановка процесса; для будущего
  multi-user — maintenance mode).
- **SQLite/Chroma не транзакционны вместе**: фаза 1 не трогает Chroma вообще;
  Chroma-миграция — отдельная фаза (Step 4) со своим report.

## 7. (Этап 3) Что войдёт в migrate.py — превью

- Фаза pre: backup, lock; фаза 1: backfill NULL→'default', rebuild
  documents/conversations с NOT NULL; integrity: `PRAGMA foreign_key_check`,
  счётчик NULL = 0, отчёт JSON; идемпотентность: каждый шаг проверяет
  «уже выполнено» (счётчики/PRAGMA) — повторный запуск no-op.
- Тесты: backfill значений, NOT NULL enforcement (вставка без ws → IntegrityError),
  повторный запуск no-op, backup создан, rebuild сохраняет Message и все поля.
- Backup: `backups/<timestamp>/app.db` (копия до фазы 1).
