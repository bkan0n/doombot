# Baseline Migration + Idempotent SQLSpec Migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the prod Postgres schema into `database/migrations/0001_baseline.sql` and wire SQLSpec's migration system so migrations run idempotently at bot startup and via `just migrate`.

**Architecture:** A fresh `pg_dump --schema-only` from prod is transformed into idempotent DDL (IF NOT EXISTS everywhere, constraints folded into CREATE TABLE). SQLSpec's `AsyncMigrationCommands` runs it at startup in `main.py`; the `sqlspec` CLI (configured via `[tool.sqlspec]` in pyproject.toml) runs it manually. The SQLSpec/AsyncpgConfig setup moves from `main.py` into `database/config.py` so both paths share one config.

**Tech Stack:** SQLSpec 0.52.0 (asyncpg adapter), postgres:18 (docker), just, uv.

**Spec:** `docs/superpowers/specs/2026-07-05-baseline-migration-design.md`

## Global Constraints

- **No git commits.** The user commits manually; never run `git commit` (user preference overrides the usual per-task commit steps).
- Baseline migration has **no down section** — reverting it would drop the database.
- Migration DDL must be idempotent: safe on prod (schema exists), on fresh DBs, and re-runnable.
- Local scratch databases are created inside the existing `akande-postgres-local` container (postgres 18 on port 15432, superuser `postgres`/`postgres`) so client tool versions match the server.
- Use the session scratchpad directory for all temporary dump/diff files.

---

### Task 1: Obtain a fresh prod schema dump

**Files:**
- Create: `<scratchpad>/prod-schema.sql` (temporary, not committed)

**Interfaces:**
- Produces: `<scratchpad>/prod-schema.sql` — plain-SQL schema-only dump of prod, no owners/privileges. Tasks 2 and 5 consume it.

- [ ] **Step 1: Ask the user to run pg_dump against prod**

The prod DSN is not available locally. Ask the user to run (adjusting host/user to their prod access; `--no-owner --no-privileges` keeps the dump portable; pg_dump major version must be ≥ server version — if their local pg_dump is older, run it via the prod docker host):

```bash
pg_dump --schema-only --no-owner --no-privileges "$PROD_DSN" > /path/to/scratchpad/prod-schema.sql
```

They can run it in-session with the `!` prefix. If they only have SQL-level access (no pg_dump), pg_dump is still required — reconstructing DDL from `information_schema` loses defaults/constraints. Offer the docker route: `docker exec <prod-postgres-container> pg_dump --schema-only --no-owner --no-privileges -U <user> <db>`.

- [ ] **Step 2: Verify the dump**

Run: `grep -c "CREATE TABLE" <scratchpad>/prod-schema.sql`
Expected: a positive count matching roughly the number of services (duels, gym, maps, misc, records, tags, tournament, users, xp — likely 15–40 tables).

Also check for objects needing special handling:

```bash
grep -nE "CREATE (FUNCTION|TRIGGER|VIEW|MATERIALIZED|EXTENSION|TYPE|DOMAIN)" <scratchpad>/prod-schema.sql
```

Note every hit — Task 2 must handle each kind.

### Task 2: Author `database/migrations/0001_baseline.sql`

**Files:**
- Create: `database/migrations/0001_baseline.sql`

**Interfaces:**
- Consumes: `<scratchpad>/prod-schema.sql` from Task 1.
- Produces: a SQLSpec migration file whose up-query name is exactly `migrate-0001-up`. Task 3's `script_location` points at its directory; Task 5 executes it.

- [ ] **Step 1: Create the file skeleton**

```sql
-- name: migrate-0001-up
-- Baseline: prod schema as of 2026-07-05. Idempotent — a no-op on databases
-- that already have the schema. No down migration: reverting the baseline
-- would drop the database.

<transformed DDL goes here>
```

No `migrate-0001-down` section.

- [ ] **Step 2: Transform the dump into idempotent DDL**

Apply these rules to the dump content, in order:

1. **Delete** pg_dump boilerplate: all `SET ...;` lines, `SELECT pg_catalog.set_config(...);`, `\restrict`/`\unrestrict` lines, `ALTER ... OWNER TO ...;`, `COMMENT ON SCHEMA public ...;`, and the `-- Dumped from/by` comment header. Keep pg_dump's per-object `-- Name: ...; Type: ...` comments only if they aid readability; otherwise drop them too.
2. `CREATE TABLE public.x` → `CREATE TABLE IF NOT EXISTS x` (strip the redundant `public.` qualifier everywhere — search_path covers it).
3. `CREATE SEQUENCE x` → `CREATE SEQUENCE IF NOT EXISTS x`. If a sequence exists only to serve a column default (classic serial pattern: `CREATE SEQUENCE` + `ALTER SEQUENCE ... OWNED BY` + column default `nextval(...)`), keep that trio intact but guarded — do NOT rewrite to `GENERATED ... AS IDENTITY` (changes semantics vs prod).
4. `CREATE INDEX x ON ...` / `CREATE UNIQUE INDEX x ON ...` → add `IF NOT EXISTS`.
5. **Fold constraints into CREATE TABLE.** For every `ALTER TABLE ONLY x ADD CONSTRAINT c PRIMARY KEY (...)/UNIQUE (...)/FOREIGN KEY (...)/CHECK (...)` statement, move it into table `x`'s `CREATE TABLE` body as a named table constraint (`CONSTRAINT c PRIMARY KEY (...)`) and delete the ALTER. Order table definitions so FK targets are created first (pg_dump already emits tables before FK ALTERs; after folding, reorder CREATE TABLEs topologically — parents before children). If a genuine FK cycle exists, keep those specific FKs as guarded ALTERs:
   ```sql
   DO $$ BEGIN
     IF NOT EXISTS (SELECT FROM pg_constraint WHERE conname = 'c') THEN
       ALTER TABLE x ADD CONSTRAINT c FOREIGN KEY ...;
     END IF;
   END $$;
   ```
6. `CREATE FUNCTION` → `CREATE OR REPLACE FUNCTION`. `CREATE TRIGGER t` → `CREATE OR REPLACE TRIGGER t` (postgres ≥ 14 supports it). `CREATE VIEW` → `CREATE OR REPLACE VIEW`. `CREATE EXTENSION` → `CREATE EXTENSION IF NOT EXISTS`. `CREATE TYPE`/`CREATE DOMAIN` → guarded `DO $$` block checking `pg_type`/`pg_catalog` (`IF NOT EXISTS (SELECT FROM pg_type WHERE typname = '...')`).
7. Preserve every default, NOT NULL, collation, and storage parameter verbatim. Do not "improve" the schema — the baseline must reproduce prod exactly.

- [ ] **Step 3: Sanity-check the SQL parses**

Create a scratch DB and apply the raw file body (everything below the `-- name:` line) twice:

```bash
docker exec akande-postgres-local psql -U postgres -c 'CREATE DATABASE baseline_check;'
docker exec -i akande-postgres-local psql -U postgres -d baseline_check -v ON_ERROR_STOP=1 < <scratchpad>/baseline-body.sql
docker exec -i akande-postgres-local psql -U postgres -d baseline_check -v ON_ERROR_STOP=1 < <scratchpad>/baseline-body.sql
```

Expected: both runs exit 0 (second run exercises idempotency at the SQL level). Then drop it: `docker exec akande-postgres-local psql -U postgres -c 'DROP DATABASE baseline_check;'`

Full fidelity/no-op verification happens in Task 5 through the real migration runner.

### Task 3: Wire SQLSpec config + startup migration

**Files:**
- Create: `database/config.py`
- Modify: `main.py` (lines 1–20 config block, and `main()` after `create_pool()`)
- Modify: `pyproject.toml` (add `[tool.sqlspec]` section)

**Interfaces:**
- Consumes: `database/migrations/` from Task 2.
- Produces: `database.config.spec` (SQLSpec) and `database.config.config` (AsyncpgConfig with `migration_config`) — imported by `main.py`, the CLI, and Task 5's verification runs.

- [ ] **Step 1: Create `database/config.py`**

```python
import os
from pathlib import Path

from sqlspec import SQLSpec
from sqlspec.adapters.asyncpg import AsyncpgConfig

spec = SQLSpec()
config = spec.add_config(
    AsyncpgConfig(
        connection_config={"dsn": os.environ["DSN"]},
        pool_config={"min_size": 1, "max_size": 5},
        migration_config={
            "script_location": str(Path(__file__).parent / "migrations"),
        },
    )
)
```

`Path(__file__)`-relative keeps the CLI and the bot working regardless of CWD. Before writing, confirm the exact `migration_config` key names against `sqlspec/config.py` (`script_location`, `version_table_name` are the documented keys; only `script_location` is needed).

- [ ] **Step 2: Update `main.py`**

Delete the module-level `spec = SQLSpec()` / `config = spec.add_config(...)` block (main.py lines 9–20) and import from the new module. Add the upgrade call in `main()`:

```python
from database.config import config, spec
from sqlspec.migrations.commands import AsyncMigrationCommands
```

(verify the import path — `rg "class AsyncMigrationCommands" .venv/lib/python3.14/site-packages/sqlspec/` — and prefer the shortest public path that resolves, e.g. `from sqlspec.migrations import AsyncMigrationCommands` if exported there)

```python
    await config.create_pool()
    await AsyncMigrationCommands(config).upgrade()
```

placed exactly where `await config.create_pool()` sits today (`main.py:50`), so a failed migration raises before the bot constructs or logs in. Keep the `finally: await spec.close_all_pools()`.

- [ ] **Step 3: Add `[tool.sqlspec]` to pyproject.toml**

```toml
[tool.sqlspec]
config = "database.config:config"
```

The CLI resolution order is flag → `SQLSPEC_CONFIG` env → pyproject, so this makes the bare `sqlspec` command work from the repo root.

- [ ] **Step 4: Verify imports and CLI config resolution**

```bash
uv run python -c "from database.config import config; print(config.migration_config)"
uv run sqlspec --validate-config current
```

Expected: first prints the migration_config dict; second prints "Successfully loaded 1 config(s)" and the current version (none yet) against the local DB (`DSN` must be exported from `.env` — `set -a; source .env; set +a` in bash, or rely on the justfile in Task 4).

- [ ] **Step 5: Confirm no import cycles / bot still constructs**

Run: `uv run python -c "import main"`
Expected: imports cleanly (requires `DSN` set; `BOT_TOKEN` is only read inside `main()`).

### Task 4: `just migrate` recipe

**Files:**
- Modify: `justfile`

**Interfaces:**
- Consumes: `[tool.sqlspec]` config from Task 3.
- Produces: `just migrate` — used by Task 5 and by future deploys/dev resets.

- [ ] **Step 1: Add dotenv loading and the recipe**

```just
set dotenv-load

format:
    uv run ruff check --select I --fix .
    uv run ruff check --fix .
    uv run ruff format .
    uv run pylintsql fix .

test:
    uv run pytest

migrate:
    uv run sqlspec upgrade

migrate-status:
    uv run sqlspec current --verbose
```

`set dotenv-load` exports `.env` (which holds `DSN`) to recipe processes; existing recipes are unaffected by it. Verify the CLI subcommand names first (`uv run sqlspec --help`) — use the actual names if they differ (e.g. `upgrade` may live under a `db`/`database` subgroup).

- [ ] **Step 2: Smoke-test the recipe (against local DB)**

Run: `just migrate-status`
Expected: connects to the local docker postgres and reports no applied versions (or errors cleanly if local postgres is down — start it with `docker compose up -d` first).

### Task 5: End-to-end verification

**Files:**
- Create: `<scratchpad>/local-schema.sql`, `<scratchpad>/prod-schema-normalized.sql` (temporary diff artifacts)

**Interfaces:**
- Consumes: everything above, plus `backups/doom3-2026-07-03.dump` and `<scratchpad>/prod-schema.sql`.

- [ ] **Step 1: Fresh database — migrate, then migrate again**

```bash
docker exec akande-postgres-local psql -U postgres -c 'CREATE DATABASE migrate_fresh;'
DSN=postgresql://postgres:postgres@127.0.0.1:15432/migrate_fresh uv run sqlspec upgrade
DSN=postgresql://postgres:postgres@127.0.0.1:15432/migrate_fresh uv run sqlspec upgrade
```

Expected: first run applies `0001` and creates all tables; second run reports nothing pending. (If `set dotenv-load` overrides the inline DSN, pass it via `env DSN=... just migrate` or export explicitly — inline env vars beat dotenv values, but verify.)

- [ ] **Step 2: Fidelity diff against prod**

```bash
docker exec akande-postgres-local pg_dump --schema-only --no-owner --no-privileges -U postgres migrate_fresh > <scratchpad>/local-schema.sql
```

Normalize both dumps (strip `SET` lines, comments, blank lines, the SQLSpec version-table objects, sort? No — keep order-sensitive compare loose): compare object-by-object rather than textually if ordering differs. Minimum bar:

```bash
grep -E "^(CREATE TABLE|CREATE.*INDEX|ALTER TABLE|CREATE SEQUENCE|CREATE (OR REPLACE )?(FUNCTION|TRIGGER|VIEW))" <scratchpad>/prod-schema.sql  | sort > /tmp1
grep -E "^(CREATE TABLE|CREATE.*INDEX|ALTER TABLE|CREATE SEQUENCE|CREATE (OR REPLACE )?(FUNCTION|TRIGGER|VIEW))" <scratchpad>/local-schema.sql | sort > /tmp2
diff /tmp1 /tmp2
```

plus a column-level check via `psql -c '\d+ <table>'` on a few complex tables. Expected: only differences are the SQLSpec version table and `public.` qualifier cosmetics. Any real difference (missing column, wrong default, missing index/constraint) → fix `0001_baseline.sql`, drop `migrate_fresh`, repeat from Step 1.

- [ ] **Step 3: Prod-rollout simulation against the restored backup**

```bash
docker exec akande-postgres-local psql -U postgres -c 'CREATE DATABASE migrate_prodsim;'
docker exec -i akande-postgres-local pg_restore -U postgres -d migrate_prodsim --no-owner --no-privileges < backups/doom3-2026-07-03.dump
DSN=postgresql://postgres:postgres@127.0.0.1:15432/migrate_prodsim uv run sqlspec upgrade
```

Expected: upgrade completes without error on a database that already has the full schema (this is exactly what prod will experience), and `sqlspec current` afterwards reports `0001`. If the July 3 backup's schema differs from today's prod dump, expect the migration to *create* the delta objects — note them, they're schema changes made since the backup, and confirm they match reality.

- [ ] **Step 4: Startup-path check**

Run the bot entrypoint far enough to hit the migration (no BOT_TOKEN needed if it fails after migrate — instead, exercise just the migration call):

```bash
DSN=postgresql://postgres:postgres@127.0.0.1:15432/migrate_fresh uv run python -c "
import asyncio
from database.config import config
from sqlspec.migrations.commands import AsyncMigrationCommands

async def go():
    await config.create_pool()
    try:
        await AsyncMigrationCommands(config).upgrade()
    finally:
        await config.close_pool()

asyncio.run(go())
"
```

Expected: completes with 'nothing to upgrade' (version already applied) — proves the exact startup code path works.

- [ ] **Step 5: Cleanup + repo hygiene**

```bash
docker exec akande-postgres-local psql -U postgres -c 'DROP DATABASE migrate_fresh;'
docker exec akande-postgres-local psql -U postgres -c 'DROP DATABASE migrate_prodsim;'
just format
uv run pytest
```

Expected: format leaves `database/migrations/0001_baseline.sql` untouched (if `pylintsql fix .` or sqlfluff rewrites it, add the migrations directory to the sqlfluff/pylintsql exclusions in pyproject.toml and re-verify); full test suite passes. Leave committing to the user.

---

## Self-review notes

- Spec coverage: layout (T2), idempotent transform rules (T2), wiring both run paths (T3, T4), all three verification bullets (T5 steps 1–3), startup fail-fast (T3 step 2 + T5 step 4). Down-migration omission honored (T2 step 1).
- The dump's actual DDL can't be inlined in the plan (it comes from prod at execution time); Task 2 instead pins exact transformation rules per object type, which is the complete "how".
- Command names (`sqlspec upgrade`, import path for `AsyncMigrationCommands`) carry an explicit verify-first instruction because SQLSpec's public API surface was only partially confirmed during planning.
