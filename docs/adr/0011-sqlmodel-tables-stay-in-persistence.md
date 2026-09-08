# ADR 0011: a SQLModel table never leaves `persistence/`

## Status

Accepted.

## Context

SQLModel's whole pitch is that the table class *is* the Pydantic model —
one class, used as both the ORM row and the API/domain shape, no converter
layer. This repo does not take that offer. `packages/adapters/.../
persistence/tables.py` defines nine `SQLModel, table=True` classes; every
repository method in `repositories.py` converts each row to (or from) the
matching frozen dataclass in `packages/core/.../domain/entities.py` before
returning it — `repositories.py`'s own module docstring: *"Every method
returns a frozen domain dataclass — no `SQLModel` instance ever leaves this
module."* This is the question a reader who knows the library asks first,
because it looks like deliberately declined free functionality.

## Decision

`*Table` classes are private to `persistence/`. Every port
(`packages/core/.../ports/repositories.py`) is typed in domain entities —
`Session`, `Persona`, `Turn`, and so on — never in a `SQLModel` type, and
every adapter method converts at the boundary.

Why the free convenience is declined:

- **The architecture test would fail the other way.** `packages/core` may
  import nothing beyond the standard library and `pydantic` (`ARCHITECTURE.md`
  "The rule"). A `SQLModel` table returned from a repository call would put
  `sqlmodel` — and, transitively, `sqlalchemy` — one import away from
  `packages/core`, the exact contamination the AST test exists to catch. The
  rule doesn't bend for a table that merely *looks* like a domain object.
- **`InMemorySessionRepository` and `SqlSessionRepository` share one
  contract suite** (`tests/contract/repositories/`) precisely because both
  return `Session`, never a table row on one side and a dataclass on the
  other. A `SQLModel` return type on the SQL adapter would make that shared
  suite impossible to write against a single expected shape.
- **A table's shape is a migration's shape, not a domain shape.**
  `questions_json`/`coverage_json`/`scores_json` are JSONB columns because
  Postgres needed *something* storable; `PersonaQuestion` and `Session.coverage`
  are typed, validated dataclasses because the engine needs something it can
  trust. Collapsing them into one class means every storage-layer decision
  (a new index, a renamed column, JSONB vs. a real column) becomes a change
  visible to code that has no business caring how a row is stored.

## Consequences

- Every repository method pays a conversion function
  (`_persona_from_row`-shaped helpers in `repositories.py`) that a
  SQLModel-as-domain-model design would not need. Accepted: the functions
  are small, tested once via the shared contract suite, and never touched
  by anything outside `persistence/`.
- Adding a field to a domain entity is two edits (the dataclass, the
  table + converter), not one — the cost `docs/adr/0001` already named as
  the price of ports & adapters at this size.
- A future `s3`/vector/second-database adapter for any of these ports
  never has to reconcile its own row shape with `SQLModel`'s — the port
  only ever promised a domain dataclass.
