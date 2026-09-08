# interviewer_adapters/workflow

**Responsibility** — the durable-workflow port's adapters (PRD §5). `base.py`
is the step template every step is written through once; `inline.py` runs a
workflow's steps in-process (the test engine and the local-dev engine);
`redis_streams.py` runs them via a Redis Streams consumer group, for a real
worker process (T09) to drain. `turn_steps.py` and `evaluation_steps.py` are
the two concrete workflows: `turn` (`persist_audio -> transcribe -> compose
-> synthesize -> commit_turn`) and `evaluation` (`collect_answers -> score
-> commit_report`), registered beside each other, run by *either* engine
unchanged. `sql_step_records.py` is the Postgres-backed `StepRecordStore`
`redis_streams` needs (a worker is a separate process from the one that
enqueued the run; an in-memory store cannot cross that boundary).
`temporal.py` is a stub plus `docs/adr/0003-temporal-mapping.md` — no
implementation, expansion E2/S2.

**Public surface** — `BaseStep`, `StepRecordStore`, `InMemoryStepRecordStore`,
`SqlStepRecordStore`, `build_turn_steps(...)`, `build_evaluation_steps(...)`,
`build_history(...)`, `InlineWorkflowEngine`, `RedisStreamsWorkflowEngine`
(composition roots wire these). A real `WorkflowEngine` is never imported by
name — a caller reaches one through `interviewer_core.registry.require_spec(
"workflow", settings.workflow_provider).build(settings, workflows=...,
run_repo=..., records=..., clock=..., ids=..., fail_at=...)` —
`redis_streams`'s `_build` additionally accepts `redis=` (an
`redis.asyncio.Redis`; omitted, it builds one from `settings.redis_url`).
`workflow`'s `build` takes more than `settings` (unlike every other adapter
kind) because a workflow engine needs the assembled steps and repositories,
not just credentials — that assembly is the composition root's job (T09),
not this module's.

**Depends on** — `interviewer_core.ports.workflow`, `.repositories`,
`.speech`, `.storage`, `.llm`, `.clock`, `.ids`; `interviewer_core.domain`;
`interviewer_core.engine` (`TurnPipeline`, `evaluate`); `interviewer_core.errors`;
`interviewer_core.registry`; `redis.asyncio` (`redis_streams.py` only,
imported lazily inside `_build` so nothing else in this package pays for it).

**Invariants** — the four of PRD §5.2, each enforced in a specific place:

1. **Idempotent start** — `InlineWorkflowEngine.start()` looks up the run by
   `idempotency_key` first; a second `start()` with the same key returns the
   same run, never a second one. Prevents a double-tap on send from opening
   two runs for one turn.
2. **Deterministic replay** — `BaseStep.run()` reads only `ctx.input` and
   `ctx.outputs`; `reply_mode` is captured once into `ctx.input` at the
   caller's `start()`, never read live from `Settings` inside a step.
   Prevents a flag flip mid-flight from changing what a replay produces.
3. **Checkpoint before ack** — `BaseStep.execute()` (the template method)
   saves the step's output to `StepRecordStore` *before* returning it; the
   engine only advances past a step once that save has completed. Prevents
   at-least-once delivery from re-paying for (or re-writing) a step that
   already succeeded.
4. **Classified failure** — each engine's own `_drive()` catches `PortError`
   around `step.execute()`: `transient=True` and attempts under
   `step.max_attempts` retries — `inline` in-process with jittered backoff,
   `redis_streams` by scheduling the retry onto a per-workflow `:delayed`
   `ZSET` and returning immediately (no `asyncio.sleep` holding a consumer
   slot); anything else fails the run at once, `run.error` names the step,
   and `redis_streams` additionally pushes the raw stream entry onto
   `:dlq`. Prevents an unclassified retry loop from hammering a
   permanently-broken dependency. **Any exception `step.execute()` raises
   that is not a `PortError`** — a `DomainError` from a step's own logic, for
   example — is caught by the same `_drive()` and treated as a permanent,
   non-retryable failure too, never re-raised past the engine. Found live
   (T10): before this branch existed, a non-`PortError` propagated out of
   `_drive()` and killed the worker process outright — one bad step failed
   every run after it, not just its own. Both `inline._drive()` and
   `redis_streams._drive()` carry this branch; a new engine adapter must
   too, or a single malformed provider response can take the whole worker
   down.

**Where to change what** — add a workflow step → a new `BaseStep` subclass in
`turn_steps.py`/`evaluation_steps.py` (or a new file, for a third workflow),
appended to the matching `build_*_steps()` tuple; the template method never
changes. Add an engine → a new module here registering
`kind="workflow"`, plus one import line appended to this package's
`__init__.py` and to `interviewer_adapters/__init__.py`.

**Traps** — the two `Turn` rows a round produces share no speaker field on
the frozen domain (T02); this lane assigns them by index parity off
`ctx.input["turn_index"]` (n): candidate = `2n`, interviewer = `2n + 1`.
`build_history()` depends on this convention to reconstruct `HistoryTurn`
pairs — a caller that writes turns any other way breaks both the evaluator
and the next `compose` call's context. `commit_report` requires the session
already be in phase `evaluating` (`advance(..., "complete")` raises
otherwise) — the caller (T09's Finish endpoint) must apply
`start_evaluation` and persist it *before* starting the evaluation workflow.
`WORKFLOW_PROVIDER=inline` still checkpoints only in memory
(`InMemoryStepRecordStore`) — it does not survive a process restart, which
is fine for tests and for a single-process local demo, but T09's
composition root must wire `redis_streams` through `SqlStepRecordStore`,
never `InMemoryStepRecordStore`, or a worker restart loses every
checkpoint. `SimulatedCrash` is a test-only escape hatch (`fail_at`);
production code never raises it and never catches it.

`redis_streams.start()` does **not** run a workflow's steps — it enqueues
and returns; a worker calls `consume_once()` in a loop to actually drive
runs (T09's worker process). A test (or a caller) that expects `start()`
to have finished the run, the way `inline.start()` does, will see
`RunState.status` still `"running"` until something drains the stream.
`consume_once()`'s `_reclaim_stale()` runs `XAUTOCLAIM` with
`min_idle_time=WORKFLOW_VISIBILITY_TIMEOUT_SECONDS * 1000` on *every* call,
including the very first from a brand-new consumer — a low visibility
timeout in a test is what makes lease-recovery observable without a real
120-second wait. A transient step failure's retry count is tracked as a
`"pending"` `WorkflowStepRecord` (the `StepStatus` literal's third value)
precisely because the retry crosses `consume_once()` calls, possibly
different processes — `inline` never needs this since its retry loop stays
inside one `_drive()` call, on one local variable.
