# packages/core

**Responsibility** — the pure domain, the interview engine and the port
catalogue: `Session`/`Turn`/`Persona`/`Artifact`/`InterviewInvite` and their
state machines, every `typing.Protocol` an adapter implements, the provider
registry, settings and logging. It owns zero I/O — no database, no HTTP
client, no queue.

**Public surface** — `interviewer_core.domain`, `interviewer_core.ports`,
`interviewer_core.engine`, `interviewer_core.registry`,
`interviewer_core.config`, `interviewer_core.logging`, `interviewer_core.errors`.
Populated starting with the settings/errors/domain/ports/registry task; see
this package's git history for what has landed.

**Depends on** — nothing outside the standard library and `pydantic`
(including `pydantic-settings`). Not `sqlmodel`, not `httpx`, not `redis`,
not any adapter package.

**Invariants** — this package imports nothing outside the standard library,
`pydantic`, or itself; a unit test walks its AST and fails, naming the
offending import, if that is violated. No provider name appears anywhere in
this package. No `if/elif` dispatches on a provider slug — the registry does.

**Where to change what** — a new external concern → a `Protocol` in `ports`
plus its fake; a new entity or state transition → `domain`; a new provider
kind → a row in `registry`'s vocabulary, not a branch; logging or settings
shape → `config` / `logging`.

**Traps** — `pydantic-settings`'s import name is `pydantic_settings`, not
`pydantic`; it is allowed here deliberately (see
`docs/adr/0002-core-logging-without-structlog.md` for the logging half of
this same boundary). `sqlmodel` looks like a pydantic library and is not
one of the two allowed imports — the purity test names it specifically
because it is the mistake most likely to slip past a quick read.
