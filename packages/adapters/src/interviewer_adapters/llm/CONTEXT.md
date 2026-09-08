# interviewer_adapters/llm

**Responsibility** — every provider behind `interviewer_core.ports.llm.LLMPort`:
`openrouter`, `openai_compat`, and the scripted `fake` used by every other
lane's unit suite and by a clean clone with no API key. Also the
cross-cutting wrappers (`RetryingLLM`, `RateLimitedLLM`, `InstrumentedLLM`)
the composition root stacks around whichever one `LLM_PROVIDER` names.

**Public surface** — nothing here is imported by name outside this package
and its tests. A caller reaches a provider through
`interviewer_core.registry.require_spec("llm", settings.llm_provider).build(settings)`,
and reaches a decorator by importing the class directly from
`interviewer_adapters.llm.decorators`.

**Depends on** — `interviewer_core.ports.llm`, `interviewer_core.errors`,
`interviewer_core.registry`, `interviewer_core.config.Settings`,
`interviewer_core.logging`; `httpx.AsyncClient` for the two real adapters.

**Invariants** — no adapter lets an `httpx` exception escape `complete()`;
every failure maps onto `PortError(transient, status)`, with 429/5xx
transient and 400/401 not. A missing credential raises `ConfigError` naming
the exact env var, at `build()` time, before any call is attempted. `fake`
refuses to build under `APP_ENV=prod`.

**Where to change what** — add a provider → one new module in this
directory that builds an `LLMPort` and calls `register(ProviderSpec(...))`
at import time, plus one import line appended to this package's
`__init__.py` and to `interviewer_adapters/__init__.py`. Never add an
`if/elif` on a provider slug anywhere.

**Traps** — `openrouter.py` and `openai_compat.py` share their transient-status
set and content/usage parsing shape on purpose (interchangeable via one env
flip); do not let them drift without a reason. The decorators wrap `LLMPort`
and are composed *outside* the adapter, in the app's composition root — they
do not belong inside `openrouter.py` or `openai_compat.py`.
