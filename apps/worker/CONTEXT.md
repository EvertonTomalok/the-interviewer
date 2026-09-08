# apps/worker

**Responsibility** — the workflow consumer process. Under
`WORKFLOW_PROVIDER=redis` it drains both durable workflows (`turn`,
`evaluation`) through `RedisStreamsWorkflowEngine.consume_once`, duck-typed
so this module never imports a provider by name. Under `WORKFLOW_PROVIDER=
inline` there is nothing to drain — the API already drove every run inside
its own request via `interviewer_api.deps.spawn()` — so this process just
stays up for `docker compose`'s health check and exits cleanly on shutdown.

**Public surface** — `python -m interviewer_worker` is the only entrypoint;
nothing here is meant to be imported by another app.

**Depends on** — its own `src/interviewer_worker/deps.py` (a trimmed copy of
`apps/api/src/interviewer_api/deps.py`: same providers/repositories/pipeline/
workflow engine, no auth, no passkeys — this process has no routes and no
bearer tokens).

**Invariants** — a step reads only `ctx.input` and `ctx.outputs`, never the
clock, never a fresh repository read a previous step could have produced as
output. A completed step's output is checkpointed before the message is
acknowledged, so an at-least-once redelivery never re-runs paid work. The
drain loop knows the two workflow **names**, `turn` and `evaluation`, never
what a step inside either one does.

**Where to change what** — a new provider/repository this process needs → a
`@lru_cache` getter in `deps.py`, appended at the end of its section (kept in
sync with `interviewer_api.deps` by hand — the two are deliberately not
shared, see Traps); consumer-loop behaviour (lease recovery, retry backoff,
dead-letter routing) → the `redis_streams` adapter, not here; a new workflow
to drain → add its name to `_WORKFLOWS` in `__main__.py`.

**Traps** — `_drain_loop` reads `consume_once` off the engine via `getattr`
and calls it **directly** (`await consume(...)`), not `consume.consume_once
(...)` — `consume` already *is* the bound method; the doubled call was a
real bug caught by `tests/test_drain_loop.py`, worth re-reading before
touching this function again. This app's `deps.py` and the API's are two
independent composition roots by design (no cross-app import) — a provider
added to one does not exist for the other until added here too.
