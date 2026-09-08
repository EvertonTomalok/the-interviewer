# ADR 0005: workflow checkpoints live in Postgres, not Redis

## Status

Accepted.

## Context

`redis_streams.py` already uses Redis for two things: the stream (queue) and
the delayed-retry `ZSET`. `WorkflowStepRecord` — the memoized output that
`BaseStep.execute()` checks before running a step again — could have lived
there too: one fewer moving part, one round trip instead of two per step.

## Decision

Checkpoints go through `SqlStepRecordStore` into `workflow_step_records`
(Postgres), never into Redis. Redis is transport and lease only — "Redis is
transport and lease; Postgres is the durable truth" (`sql_step_records.py`'s
own docstring, quoting PRD §5.3).

The reasons, in the order they'd bite:

- **A restarted Redis is not a restarted worker.** `docker kill` on the
  worker mid-run is the durability drill (PRD §12.4); a flushed or evicted
  Redis instance is a separate failure the design should survive too. If the
  checkpoint lived in Redis, losing Redis would also lose the memo of which
  steps already ran — the exact state a checkpoint exists to protect.
- **`inline` and `redis_streams` share one checkpoint contract.** Both
  engines call the same `StepRecordStore.get`/`save` through the same
  `BaseStep.execute()`. `inline`'s tests run on `InMemoryStepRecordStore`;
  local dev and `redis_streams` run on the same `SqlStepRecordStore`. A
  Redis-only checkpoint would need its own store implementation that
  `inline` cannot use, breaking the "both engines pass the identical
  contract suite" property T09/T10's tests rely on.
- **Retention and inspection are already Postgres's job.** `workflow_runs`
  and `workflow_step_records` are read by the admin listing and by anyone
  debugging a stuck run with `SELECT`. Redis has no query language for that
  and no retention policy beyond what the operator bolts on.

## Consequences

- Every step pays one Postgres round trip to check and one to checkpoint,
  in addition to the Redis `XADD`/`XACK`. Accepted: steps call an LLM or an
  STT provider, so a Postgres write is not the expensive part of a turn.
- Flushing Redis loses queued/in-flight delivery, not history — a run stuck
  mid-stream after a flush can be manually re-enqueued from its
  `workflow_runs` row without re-paying for completed steps.
- The `temporal` adapter (`docs/adr/0003`) needs no `StepRecordStore` at
  all — Temporal's own event history replaces it. This ADR's decision is
  specific to the two adapters that do not have that for free.
