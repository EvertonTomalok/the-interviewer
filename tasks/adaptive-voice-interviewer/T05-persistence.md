# T05 — Persistence (SQL + in-memory repositories)

**Wave 1 · lane C · depends on T02 · runs in parallel with T03, T04, T06 · covers PRD §11 T7**

> **Start this lane first inside wave 1.** T07 cannot begin without the
> `workflow_runs` / `workflow_step_records` tables, and T09 cannot begin without
> the repositories.

```bash
git worktree add ../wt-t05-persist -b task/t05-persistence master
```

**Owns:** `packages/adapters/src/interviewer_adapters/persistence/**`,
`migrations/**` (the Alembic chain plus its `env.py` and script template), its
`CONTEXT.md`, its tests. **Appends only** to `alembic.ini`,
`interviewer_adapters/__init__.py` and `.env.example`.

## Reference in this repo

| Read | For |
|---|---|
| `packages/shared-py/src/ama_shared/db/repos.py` | repository methods that return domain objects, not rows; narrow reads; a `find_by_id` that distinguishes "absent" from "broken" |
| `packages/shared-py/src/ama_shared/db/ports.py` | the repository seam itself — what the layer above is allowed to know |
| `packages/shared-py/src/ama_shared/db/tables.py`, `agent_tables.py` | table definitions with unique constraints doing real work, and versioned configuration rows that are never edited in place — the same table layer this lane writes in SQLModel |
| `packages/shared-py/src/ama_shared/db/engine.py` | one async engine and session scope, created once, injected — never a module-level connection |
| `packages/shared-py/src/ama_shared/db/piccolo_migrations/` | migrations as an ordered chain, each re-runnable on a half-applied database: `DROP CONSTRAINT IF EXISTS` before `ADD`, cleanup before constraining. That repo uses a different migration tool — copy the discipline, not the API; here the chain is Alembic |
| `packages/shared-py/src/ama_shared/db/leases.py` | a lease row that lets one worker claim work and another reclaim it after a timeout — the same idea T07 implements over Redis |

## Deliverables

### Schema + migrations

Every entity of PRD §4. Constraints that carry meaning, not decoration:

- `UNIQUE (session_id, index)` on `turns` — the database, not the engine, is what
  makes a duplicated turn impossible under at-least-once delivery.
- `UNIQUE (idempotency_key)` on `workflow_runs` — a double-tap on **send** joins
  the existing run instead of opening a second one.
- `UNIQUE (run_id, name)` on `workflow_step_records` — one record per step per
  run, which is what makes replay memoization sound.
- `UNIQUE (area_id, version)` on `personas`, with a status. A session stores
  `persona_version_id`; so does the report. **No update-in-place of a published
  version.**
- `UNIQUE (session_id)` on `interview_reports` — one interview, one report. The
  evaluation workflow's `commit_report` upserts on it, so a replay after a crash
  rewrites the same row instead of stacking a second verdict on the same session.
- `UNIQUE (slug)` on `interview_invites`, plus `passkey_hash`, `expires_at`,
  `max_sessions`, `used_count`, `status`. **No plaintext passkey column exists** —
  there is nowhere to put one, which is the strongest form of "never store it".
- An `artifacts` table beside the blobs: `session_id`, `mime`, `size_bytes`,
  `checksum`, `uri`, indexed on `session_id`. The bytes live in the blob store
  (T06); this row is what `GET /session/artifacts/{id}` checks ownership against
  before streaming anything, and it is written by the run's `persist_audio` step,
  not by the request that uploaded the file.
- An index on `sessions (created_at DESC)` and on `(area_id, phase)`: the admin
  list is the one read that grows without bound, and it is the read a reviewer
  does every day.

There are **no knowledge tables and no guide table**: the persona holds the
questions, the expected answers and the rubric as versioned JSON columns. When
expansion `E1` adds a corpus it adds `knowledge_documents` /
`knowledge_chunks` in its own migration — do not create them empty now.

Migration rules, learned the expensive way and worth restating: clean the data
before you constrain it; every migration re-runnable on a half-applied database;
a migration that already ran gets a **new** file, never an edit.

**Alembic is the chain**, wired to SQLModel rather than to hand-written
metadata: `env.py` imports `persistence.tables` (an empty `SQLModel.metadata` is
the classic first failure — autogenerate then cheerfully proposes dropping
everything), sets `target_metadata = SQLModel.metadata`, and runs migrations
through the async engine with `connection.run_sync`. The `script.py.mako`
template gains `import sqlmodel`, because autogenerate emits
`sqlmodel.sql.sqltypes.AutoString` for every string column and a generated file
that does not import it fails at `upgrade head`, not at review time.

### Tables — SQLModel, and only here

Every entity of PRD §4 gets a **SQLModel** table class in
`persistence/tables.py`. SQLModel is the declarative layer — pydantic field
types over SQLAlchemy 2.x async, `asyncpg` underneath — so a table reads almost
like the domain dataclass it mirrors, and that resemblance is the trap this lane
must not fall into. **A table is not a domain object.** It never leaves this
package: the repository maps it into the frozen dataclasses of T02 before
returning, and back on write. Handing the table upward would give the core a
SQLAlchemy import, an identity map, and lazy attributes that raise once the
session is closed — three things the engine was designed never to know about.

What SQLModel does *not* do for you, and this lane must state explicitly:

- **JSON columns are declared, not inferred.** `questions_json`, `rubric_json`,
  `coverage_json`, `usage_json` and the workflow payloads are
  `Field(sa_column=Column(JSONB, nullable=False))`. A bare `dict` field has no
  column type for SQLModel to guess, and Postgres `JSON` is not `JSONB`.
- **Composite constraints live in `__table_args__`** —
  `UniqueConstraint("session_id", "index")`, `UniqueConstraint("run_id", "name")`,
  `UniqueConstraint("area_id", "version")` — together with the two indexes above.
  `Field(unique=True)` covers only the single-column cases: `slug`,
  `idempotency_key`, and `session_id` on reports.
- **The session type is `sqlmodel.ext.asyncio.session.AsyncSession`**, produced
  by an injected session factory over one `create_async_engine`. No module-level
  engine, and no repository method that creates its own session.
- **Phase and kind are text columns with the check in the domain**, not Postgres
  enums. Both vocabularies grow with the expansions, and `ALTER TYPE` in a
  migration takes a lock nobody wants for a rule the phase machine already
  enforces.

### Repository adapters

Async implementations of the repository ports —
`User`, `Area`, `Persona`, `Invite`, `Session`, `Turn`, `Artifact`, `Run`, `Report` —
written with SQLModel's typed `select()`, dropping to plain SQLAlchemy where
SQLModel adds nothing (the atomic claim below is exactly that). Sessions come
from an injected session factory. They return domain dataclasses; **no table
instance escapes the adapter.**

**`InviteRepository.claim(slug, now)` is the one method with teeth.** It must
check `status`, `expires_at` and `used_count < max_sessions` **and** increment
`used_count` in a single atomic statement — a conditional `UPDATE … WHERE
used_count < max_sessions … RETURNING`, not a read followed by a write. Two
candidates opening the last slot at the same second is exactly the race this
repository exists to lose safely, and the in-memory twin enforces it under a lock
so the contract suite can assert it in both.

### In-memory twins

Dict-backed implementations of **the same ports**, with the same uniqueness
enforcement — a second turn at an existing index raises the same error type as
Postgres would. These are what every other lane's unit suite runs on. If they
are lenient where Postgres is strict, the whole test suite is a comfortable lie.

### One shared contract suite

`tests/contract/repositories/` is parametrised over both implementations. It is
the deliverable that matters most in this lane: the SQL run is marked
`integration` (needs a container), the in-memory run is part of `make check`.

## Tests

- Contract suite, both implementations: create/read/update, absent id, uniqueness
  violations (`(session_id, index)`, `idempotency_key`, `(run_id, name)`,
  `session_id` on reports), ordering of turns by index.
- Versioning: publishing persona v2 leaves v1 readable, leaves a session pinned
  to v1 pointing at v1, and leaves a report written under v1 unchanged.
- A persona round-trips its questions with `expected_answer`, `weight` and
  `follow_up_depth` intact, and its `greeting_text` / `intake_prompt_text` /
  `farewell_text` verbatim — the JSON column is loaded back as the domain
  dataclasses, not as raw dicts leaking into the engine.
- **Invite claim under contention**: `max_sessions=1`, two concurrent claims —
  exactly one wins, `used_count` ends at 1. Run it on both implementations; the
  SQL one is where a read-then-write would pass every serial test and fail here.
- An invite past `expires_at`, one with `status="retired"` and one with
  `used_count == max_sessions` all refuse the claim, each with its own reason.
- Session phase persists and rejects an illegal move; `candidate_name` survives a
  round-trip; the admin listing query returns newest first and pages stably.
- Migrations apply to an empty database and are re-runnable (integration marker).
- **The boundary, asserted by type**: every repository read returns a domain
  dataclass — `isinstance(got, Session)` and *not* a `SQLModel` instance. This is
  the test that fails the day someone returns the table because "it serialises
  fine anyway", and it is cheaper than the incident where a lazy attribute raises
  inside the engine.
- JSON columns round-trip as `JSONB`: a persona with unicode text, nested
  question objects and an empty rubric comes back identical, and a `dict` written
  through one repository is queryable by key in SQL (the check that the column is
  not plain text).
- `alembic check` reports no pending autogenerated diff — the chain and
  `SQLModel.metadata` describe the same schema, so a table field added without a
  migration fails the build instead of the deploy (integration marker).

## Done when

- In-memory and SQL repositories pass **one** shared contract suite.
- `make check` (no container) is green using the in-memory twins.
- `make migrate` builds the schema on a fresh Postgres from `docker compose`.
- **`sqlmodel` is imported nowhere outside `persistence/`** — one grep in the
  suite proves it, and T02's purity test proves the core never sees it.
- `persistence/CONTEXT.md` names the unique constraints under **Invariants**,
  each with the failure it prevents.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t05-persist
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(persistence): schema, repositories and one contract suite (T05)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t05-persistence -m "feat(persistence): schema, repositories and one contract suite (T05)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t05-persist
git branch -d task/t05-persistence
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
