# ADR 0003: the Temporal mapping (why the port is designed for it, and why it isn't built yet)

## Status

Accepted. `temporal.py` is a stub; the real adapter is expansion E2/S2.

## Context

PRD §5.3 requires that swapping `WORKFLOW_PROVIDER` cost one adapter and
zero engine changes -- Redis today, Temporal in production tomorrow. That
claim is only real if the `WorkflowEngine`/`BaseStep` port (T02, frozen)
could not have been designed any other way without breaking a Temporal
implementation later.

## Decision

The mapping, checked against every piece of the port:

| Port concept | Temporal concept |
|---|---|
| `BaseStep.run(ctx)` | an **Activity** function |
| `BaseStep.execute()`'s memoized checkpoint | Temporal's own event history (a real Temporal adapter needs no `StepRecordStore` at all) |
| `idempotency_key` | the **Workflow Id**, with a reject-duplicate `WorkflowIdReusePolicy` |
| `max_attempts` | a `RetryPolicy` on the Activity |
| `PortError(transient=True)` | a retryable Activity failure |
| `PortError(transient=False)` | a non-retryable Activity failure -> Workflow `Failed` |
| `inline`'s/`redis_streams`'s hand-rolled `:dlq` stream | not needed -- a `Failed` Workflow already is the durable, human-readable record |

Nothing on the port names a provider, a queue, or a checkpoint store by
name; every adapter-specific piece (Redis stream/group/ZSET, Postgres
`workflow_step_records`) lives in `redis_streams.py`, not in the port. A
Temporal adapter would implement `start()`/`status()`/`cancel()` against
the Temporal client SDK and register each `BaseStep` subclass's `run()` as
an Activity -- no change to `packages/core`.

## Consequences

- Building the real adapter later is additive: a new file plus one
  registration line, exactly like every other provider.
- `redis_streams._drive()`'s retry/backoff/DLQ logic is adapter-specific
  scaffolding that a Temporal adapter would delete, not port -- Temporal
  does that job itself. This is expected, not a sign the port leaked
  Redis-specific assumptions.
