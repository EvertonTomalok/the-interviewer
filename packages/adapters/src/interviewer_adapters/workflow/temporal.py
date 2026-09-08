"""`WORKFLOW_PROVIDER=temporal` -- not implemented (expansion E2/S2).

This module exists so the `WorkflowEngine`/`BaseStep` port cannot quietly
drift into a shape Temporal could not implement. The mapping, recorded here
and in `docs/adr/0003-temporal-mapping.md`:

- `BaseStep` -> a Temporal **Activity**. `run()`'s signature (reads only
  `ctx.input`/`ctx.outputs`, returns a `Mapping`) is already what an
  Activity function looks like; `execute()`'s memoized-checkpoint shape is
  exactly what Temporal's own event history gives an Activity for free --
  a real Temporal adapter would not even need `StepRecordStore`.
- `idempotency_key` -> the Workflow Id, with a `WorkflowIdReusePolicy`
  that rejects a duplicate while one is running -- the same "same key,
  same run" guarantee `inline` and `redis_streams` enforce by hand against
  `RunRepository`.
- `max_attempts` -> a Temporal `RetryPolicy` on the Activity, which already
  does transient/permanent classification and jittered backoff -- the
  engine-level retry loop in `redis_streams._drive()` would not exist here
  at all.
- `PortError.transient` -> whether the Activity's exception is retryable;
  a non-transient `PortError` would be raised as a non-retryable Activity
  failure, landing the Workflow in a `Failed` state Temporal already
  surfaces (no hand-rolled `:dlq` stream needed).

No client, no worker, no registration. Building the real adapter is
expansion `E2`/`S2`.
"""

from __future__ import annotations
