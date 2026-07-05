# Baseline Migration + Idempotent SQLSpec Migrations

**Date**: 2026-07-05
**Status**: Approved

## Goal

Bring the production database under migration control. The prod schema becomes
the first migration, and all future schema changes flow through SQLSpec's
migration system. Applying migrations is idempotent: safe to run on prod (which
already has the schema), on a fresh database, and repeatedly.

## Current state

- SQLSpec 0.52.0 with `AsyncpgConfig` wired up in `main.py`; pool created at
  startup, `DSN` from env.
- No migrations directory; schema changes have been applied to prod by hand.
- Prod runs postgres:18 (docker-compose). A local docker postgres exists for
  dev, plus a prod backup at `backups/doom3-2026-07-03.dump`.
- The `sqlspec` CLI ships with the venv and supports `init`, `revision`,
  `upgrade`, `downgrade`, `stamp`, `current`. Applied versions are tracked in a
  version table, so `upgrade` only runs pending migrations.

## Design

### Migration layout

- New directory: `database/migrations/`.
- First migration: `database/migrations/0001_baseline.sql` (sequential
  versioning; SQLSpec supports it alongside timestamps).
- SQLSpec native file format: a `-- name: migrate-0001-up` section.
- **No down section for the baseline.** Reverting it means dropping the entire
  database; that should never be one command away.

### Idempotent baseline

Source of truth: a fresh `pg_dump --schema-only` from prod (not the July 3
backup). The dump is transformed into idempotent DDL:

- Strip pg_dump noise: `SET` statements, `ALTER ... OWNER`, `COMMENT ON`
  boilerplate, `SELECT pg_catalog.set_config(...)`.
- `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`,
  `CREATE SEQUENCE IF NOT EXISTS`.
- Fold the separate `ALTER TABLE ... ADD CONSTRAINT` statements pg_dump emits
  (primary keys, foreign keys, uniques) back into the `CREATE TABLE` bodies, so
  `IF NOT EXISTS` covers them and no `DO $$` guard blocks are needed.
- Functions/triggers (if any) become `CREATE OR REPLACE` / guarded equivalents.

Result: `upgrade` against prod is a no-op that records version 0001; against a
fresh database it builds the full schema.

### Wiring

- `migration_config={"script_location": "database/migrations"}` on the existing
  `AsyncpgConfig`.
- **Startup path**: `main.py` runs `AsyncMigrationCommands(config).upgrade()`
  after `create_pool()`, before the bot starts. A failed migration means the
  bot refuses to start (fail fast).
- **Manual path**: `just migrate` recipe wrapping the `sqlspec` CLI. Reads
  `DSN` from env, so the same recipe targets local dev or prod.

### Version table

SQLSpec's default version table name; no override.

## Verification

1. **Fresh + idempotent**: spin up a clean local postgres, run `upgrade`, then
   run `upgrade` again. First run builds the schema; second is a recorded
   no-op.
2. **Faithful**: `pg_dump --schema-only` the migrated local DB and diff
   (normalized) against the prod schema dump. The baseline must reproduce prod
   exactly.
3. **Safe prod rollout**: restore the prod backup into a local DB, run
   `upgrade` against it. Must complete as a no-op and record version 0001 —
   this simulates the actual prod deployment.

## Error handling

- Startup migration failure aborts boot before the bot logs in.
- Migrations run through SQLSpec's runner, which records each version only
  after successful application.

## Out of scope

- No data migration; schema only.
- No changes to existing service classes or queries.
- Future migrations: authored via `sqlspec revision`, applied via startup hook
  or `just migrate`. Not part of this work beyond the machinery existing.
