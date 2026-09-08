# apps/worker

**Responsibility** — the workflow consumer process: drains the Redis stream
(or runs `inline` in dev/test), executes each `WorkflowStep` through the
shared checkpoint-before-ack template method, and shuts down gracefully on
`SIGTERM`/`SIGINT`. Same core, same adapters as the API — no HTTP surface of
its own.

**Public surface** — `python -m interviewer_worker` is the only entrypoint;
nothing here is meant to be imported by another app.

**Depends on** — `WorkflowEngine`, `WorkflowStep`, `StepContext` from
`interviewer_core.ports`, plus whatever port each step calls (LLM, STT, TTS,
`BlobStore`, the repositories).

**Invariants** — a step reads only `ctx.input` and `ctx.outputs`, never the
clock, never a fresh repository read a previous step could have produced as
output. A completed step's output is checkpointed before the message is
acknowledged, so an at-least-once redelivery never re-runs paid work.

**Where to change what** — a new step → the pipeline module that owns it,
registered in the pipeline's step list, tested in the shared
crash-after-*k* contract suite; consumer-loop behaviour (lease recovery,
retry backoff, dead-letter routing) → the `redis_streams` adapter, not here.

**Traps** — this module currently does nothing but log and wait for a
shutdown signal; there is no workflow adapter wired in yet. Do not read the
placeholder loop as the shape the real consumer will take.
