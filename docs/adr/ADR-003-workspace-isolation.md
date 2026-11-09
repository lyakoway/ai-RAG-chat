# ADR-003: Workspace isolation strategy (nullable → backfill → rebuild → mandatory scope)

- **Status:** Accepted (implemented; production migration executed 2026-11-09)
- **Date:** 2026-11-08 (plan v1.1), migration 2026-11-09
- **Deciders:** project maintainer

## Context

The project started as a single-user demo: `Document`, `Conversation`,
`Message` had no owner; Chroma chunks had no workspace metadata; every API
route was unauthenticated. Multi-user RAG requires isolation of two things:
documents (SQL) and LLM context (Chroma) — the second leak is sneakier: chunks
from another workspace silently enter the prompt and get cited by the answer.

Existing data (demo pack + chat history: 18 documents, 231 conversations, 491
messages, 40 Chroma chunks) had no workspace ownership, and SQLite refuses
`ALTER TABLE ADD COLUMN … NOT NULL` without a DEFAULT — while silently
backfilling `'default'` into existing rows was explicitly rejected
(no invisible data rewrite).

## Decision

Staged, each step verifiable:

1. **Schema-only** `init_db()` — adds nullable `workspace_id` columns + indexes;
   never touches data (eternal invariant, tested).
2. **`app/db/migrate.py` phase 1** — one `BEGIN IMMEDIATE` transaction:
   backfill `NULL → 'default'`, table rebuild with `NOT NULL DEFAULT
   'default'`, index recreation; guarded by file lock, backup with
   `wal_checkpoint(TRUNCATE)` + read-only `PRAGMA integrity_check`,
   idempotent (notnull=1 ∧ NULL=0 ∧ DEFAULT present → no-op), report JSON,
   rollback on any failure.
3. **models.py** switched to `nullable=False` in the same commit as the
   migration DDL (`DEFAULT 'default'` — model and database stay in sync;
   covered by `TestModelMigrationSync`).
4. **API scoping** — `Depends(get_workspace)` (trusted backend context; demo
   mode accepts optional `X-Workspace` header — labeling, not auth), `get_scoped`
   everywhere, foreign resource → **404** (never 403 — don't reveal existence);
   unsafe direct `db.get(Message)` replaced with JOIN through Conversation.
5. **Chroma** — `workspace_id` in every chunk's metadata via `update(ids,
   metadatas)` merge (no vector re-embedding, verified on 0.5.23); mandatory
   `where={"workspace_id": …}` in query/delete; calling without workspace_id
   raises ValueError — a skipped filter is impossible, not a silent global search.

## Consequences

- Full isolation: SQL + API + Chroma. Cross-workspace access → 404; retrieval
  never returns foreign chunks (tested in both directions, including a live
  LLM negative control: chat in ws_a on a ws_b fact returns "no information" —
  the ws_b fact does not leak).
- Production migration executed 2026-11-09: SQL 249 NULL → 0 (~24 ms),
  Chroma 39 missing → 0 (~0.6 s, metadata merge), backups kept
  (`backend/backups/prod_20261109T114847Z_d818d5/`), repeated run = no-op.
- Costs: one extra column + index per table; every new retrieval path must
  propagate `workspace_id` (mandatory parameter — a skipped filter fails at
  call time); demo `X-Workspace` header is labeling, **not authentication**.

## Alternatives considered

- **`NOT NULL DEFAULT 'default'` immediately on ALTER** — rejected: silently
  rewrites existing rows (invisible data migration during schema change).
- **Full Chroma re-index with workspace metadata** — rejected: `update()`
  merge of metadata preserves vectors (verified), re-embedding 40 chunks adds
  cost for zero benefit; the merge path is verified by tests.
- **Migrate automatically on every startup** — rejected: multi-phase migration
  (SQL → Chroma → files) is not transactional across stores; a dedicated
  command with backup, lock, report and refuse-to-serve on incompatible state
  is safer.
- **403 instead of 404** — rejected: 403 confirms the resource exists.

## Evidence

- Migration reports: `backend/backups/prod_20261109T114847Z_d818d5/` (SQL
  249→0, Chroma 39→0, fk_check ok), `backend/data/backups/migration_report.json`.
- Isolation matrix: `backend/tests/test_workspace_isolation.py` (14 scenarios),
  Chroma: `backend/tests/test_chroma_isolation.py`.
- Live LLM negative control: chat ws_a on a ws_b fact → "no information"
  (fact 77777 did not leak); chat ws_b → cites 77 777 [1] (positive control).
