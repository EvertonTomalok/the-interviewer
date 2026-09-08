# packages/adapters

**Responsibility** — everything that touches the world on behalf of
`packages/core`'s ports: LLM providers, speech-to-text/text-to-speech,
blob storage, SQLModel-backed persistence, and the durable workflow engine
(Redis Streams and an in-process `inline` twin). Each adapter family lives in
its own subpackage and registers itself against `interviewer_core.registry`
by importing this package.

**Public surface** — importing `interviewer_adapters` registers every known
provider as a side effect; callers otherwise reach adapters only through
`interviewer_core.registry.require_spec(kind, name)`, never by importing an
adapter module directly.

**Depends on** — every port in `interviewer_core.ports`. Runtime
dependencies live here, not in core: `sqlmodel`, `sqlalchemy[asyncio]`,
`asyncpg`, `alembic`, `httpx`, `redis`, `bcrypt`, `pyjwt`.

**Invariants** — a SQLModel table class is not a domain object; tables stay
inside the persistence subpackage's `tables` module and repositories
translate to and from the frozen dataclasses of `interviewer_core.domain`,
both ways. No adapter lets a provider-specific exception escape its port
method — each maps its failure onto `PortError(transient, status)`.

**Where to change what** — a new provider → a new module in the matching
subpackage, registered as data, plus one import line appended to this
package's `__init__.py`; a new workflow step → the pipeline that owns it,
tested in the shared crash-after-*k* contract suite.

**Traps** — this package's `__init__.py` is append-only; reordering an
existing registration import can silently change which provider a duplicate
name resolves to first. `packages/adapters` is empty until the adapter tasks
land — this file is the scaffold, not the inventory.
