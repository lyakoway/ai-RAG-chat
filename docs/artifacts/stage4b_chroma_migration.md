# Stage 4B — Chroma migration: объяснение 39 из 40

Боевой отчёт (`backend/backups/prod_20261109T114847Z_d818d5/migration_report.json`,
chroma-фаза): `total_chunks: 40, before_missing: 39, updated: 39, after_missing: 0`.
Один чанк не был обновлён, потому что **уже имел workspace_id до миграции**.

## Разбивка 40 чанков

| Категория | Чанков | Источник |
|---|---|---|
| already_had_ws | 1 | `agent-doc.docx` (ws=`ws-a`) — загружен через API в ручной двух-workspace проверке **после** Step 3 (API isolation), **до** запуска migrate_chroma; ingestion уже писал workspace_id (Step 4 добавил его в `add_document_chunks`) |
| updated (были missing → ws=`default`) | 39 | Демо-пак и User_Guide из Stage 4A — загружены до workspace-системы; SQL-фаза 1 проставила `workspace_id='default'` в SQL, migrate_chroma разлил его в metadata чанков |
| orphan_chunks (document_id отсутствует в SQL) | 0 | Расхождения SQL↔Chroma нет |

## Подтверждение

Pre-migration backup Chroma
(`backend/backups/prod_20261109T114847Z_d818d5/chroma/`) проверен read-only
клиентом: `total=40, had_ws=1 (agent-doc, ws-a), missing=39` — совпадает с
боевым отчётом.

## Поле skipped_no_doc_id

Не путать с orphan: `skipped_no_doc_id` в отчётах migrate — SQL-записи, у
которых `workspace_id IS NULL` (фаза SQL не выполнялась); migrate_chroma их
намеренно пропускает (ws не угадывается). После SQL фазы 1 таких нет.
