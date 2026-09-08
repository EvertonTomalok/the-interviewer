# persistence

**Responsibility** — the SQLModel schema, the Alembic migration chain, the
SQL repository adapters and their in-memory twins for all nine repository
ports. Owns the one async engine and session factory.

**Public surface** — `SqlUserRepository`, `SqlAreaRepository`,
`SqlPersonaRepository`, `SqlInviteRepository`, `SqlSessionRepository`,
`SqlTurnRepository`, `SqlArtifactRepository`, `SqlReportRepository`,
`SqlRunRepository`, their `InMemory*` twins, `DuplicateKeyError`,
`make_engine`, `make_session_factory`. `tables.py` is internal — nothing
outside this package imports a table class.

**Depends on** — the nine repository ports in `interviewer_core.ports`; the
domain dataclasses they return.

**Invariants** — a table is not a domain object: every repository method
converts to/from the frozen dataclasses of `interviewer_core.domain`, both
ways. `sqlmodel` and `sqlalchemy` are imported nowhere outside this
directory. Unique constraints, each preventing a specific failure:

- `UNIQUE (session_id, index)` on `turns` — a duplicated turn under
  at-least-once workflow delivery.
- `UNIQUE (idempotency_key)` on `workflow_runs` — a double-tap on send
  opening a second run.
- `UNIQUE (run_id, name)` on `workflow_step_records` — a step recorded twice,
  which would break replay memoization.
- `UNIQUE (area_id, version)` on `personas` — a published version silently
  overwritten.
- `UNIQUE (session_id)` on `interview_reports` — a second verdict stacked on
  one interview; `commit_report` upserts on this constraint.
- `UNIQUE (slug)` on `interview_invites` — two invites answering to the same
  public link.

`InterviewInviteTable` has no plaintext-passkey column — there is nowhere to
put one. `InviteRepository.claim` is a single conditional `UPDATE … WHERE
used_count < max_sessions … RETURNING`, never a read followed by a write;
the in-memory twin enforces the same race under an `asyncio.Lock`.

**Where to change what** — a new entity or column → `tables.py`, then a new
Alembic revision (`alembic revision --autogenerate`), never an edit to a
revision already applied; a new repository method → the matching SQL class
*and* its in-memory twin, plus the shared contract suite in
`packages/adapters/tests/contract/repositories/_shared.py`.

**Traps** — `repositories.py` is omitted from the coverage floor on purpose:
it needs a real Postgres and is exercised by the SQL half of the contract
suite (`make itest`), not by the fast loop. A change here that isn't also
covered by `make itest` is unverified, coverage number notwithstanding.
`session.get()` returns `None` for a missing id and raises for anything a
unique constraint refuses — the two failure modes tests must tell apart.
