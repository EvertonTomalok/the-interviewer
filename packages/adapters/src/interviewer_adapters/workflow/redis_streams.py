"""`WORKFLOW_PROVIDER=redis`: Redis is transport and lease, Postgres is the
durable truth (PRD §5.3). Flushing Redis loses throughput, never history --
`run.status`/`WorkflowStepRecord` are what `status()` and a replay actually
trust; the stream only decides *when* a worker looks at a run again.

Unlike `inline`, `start()` does not run a workflow's steps itself -- it
enqueues and returns. A worker calls `consume_once()` in a loop (T09's
worker process) to actually drive runs. That split is why a transient
failure here is **not** retried in-process (no `asyncio.sleep` holding a
consumer slot): it is scheduled onto a per-workflow delayed-retry `ZSET`
and the consumer moves on to the next message.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal, cast

from interviewer_adapters.workflow.base import BaseStep, StepRecordStore
from interviewer_adapters.workflow.inline import FailHook
from interviewer_core.config import Settings
from interviewer_core.domain.entities import WorkflowRun, WorkflowStepRecord
from interviewer_core.errors import PortError
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import RunRepository
from interviewer_core.ports.workflow import RunHandle, RunState, StepContext, WorkflowEngine
from interviewer_core.registry import ProviderSpec, register

if TYPE_CHECKING:
    from redis.asyncio import Redis

_GROUP = "workers"
_BASE_BACKOFF_SECONDS = 0.5
_DriveOutcome = Literal["succeeded", "failed", "deferred", "crashed"]


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _field(fields: dict[Any, Any], name: str) -> str:
    """A stream entry's fields come back keyed by `str` when the client was
    built with `decode_responses=True`, `bytes` otherwise -- read either."""
    return _decode(fields.get(name, fields.get(name.encode())))


class RedisStreamsWorkflowEngine:
    """Satisfies `WorkflowEngine`. One stream per workflow
    (`workflow:{name}`), one consumer group (`workers`), a `:dlq` stream
    that is never auto-drained, and a `:delayed` `ZSET` for transient
    retries -- all keyed off the workflow name so `turn` and `evaluation`
    never share a queue."""

    def __init__(
        self,
        workflows: Mapping[str, Sequence[BaseStep]],
        *,
        redis: Redis,
        run_repo: RunRepository,
        records: StepRecordStore,
        clock: Clock,
        ids: IdGenerator,
        visibility_timeout_seconds: float = 120.0,
        fail_at: FailHook | None = None,
    ) -> None:
        self._workflows = workflows
        self._redis = redis
        self._run_repo = run_repo
        self._records = records
        self._clock = clock
        self._ids = ids
        self._visibility_timeout_ms = int(visibility_timeout_seconds * 1000)
        self._fail_at = fail_at

    def set_fail_at(self, fail_at: FailHook | None) -> None:
        self._fail_at = fail_at

    # -- naming -----------------------------------------------------------

    def _stream_key(self, workflow: str) -> str:
        return f"workflow:{workflow}"

    def _dlq_key(self, workflow: str) -> str:
        return f"workflow:{workflow}:dlq"

    def _delayed_key(self, workflow: str) -> str:
        return f"workflow:{workflow}:delayed"

    async def _ensure_group(self, stream: str) -> None:
        try:
            await self._redis.xgroup_create(stream, _GROUP, id="0", mkstream=True)
        except Exception as exc:  # redis raises ResponseError; the group already existing is fine
            if "BUSYGROUP" not in str(exc):
                raise

    # -- WorkflowEngine -----------------------------------------------------

    async def start(
        self, workflow: str, payload: Mapping[str, Any], *, idempotency_key: str
    ) -> RunHandle:
        existing = await self._run_repo.get_by_idempotency_key(idempotency_key)
        run = (
            existing
            if existing is not None
            else await self._create_run(workflow, payload, idempotency_key)
        )
        if run.status not in ("succeeded", "failed"):
            stream = self._stream_key(workflow)
            await self._ensure_group(stream)
            await self._redis.xadd(stream, {"run_id": run.id})
        return RunHandle(run_id=run.id)

    async def _create_run(
        self, workflow: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> WorkflowRun:
        now = self._clock.now()
        run = WorkflowRun(
            id=self._ids.new_id(),
            workflow=workflow,
            idempotency_key=idempotency_key,
            status="running",
            input=payload,
            error=None,
            created_at=now,
            updated_at=now,
        )
        await self._run_repo.add(run)
        return run

    async def status(self, run_id: str) -> RunState:
        run = await self._run_repo.get(run_id)
        if run is None:
            raise LookupError(f"no workflow run {run_id!r}")
        outputs: dict[str, Any] = {}
        for step in self._workflows.get(run.workflow, ()):
            record = await self._records.get(run.id, step.name)
            if record is not None and record.output is not None:
                outputs[step.name] = record.output
        return RunState(run_id=run.id, status=run.status, error=run.error, outputs=outputs)

    async def cancel(self, run_id: str) -> None:
        run = await self._run_repo.get(run_id)
        if run is None:
            raise LookupError(f"no workflow run {run_id!r}")
        cancelled = replace(run, status="failed", error="cancelled", updated_at=self._clock.now())
        await self._run_repo.update(cancelled)

    # -- worker loop --------------------------------------------------------

    async def consume_once(
        self, workflow: str, *, consumer: str = "worker-1", block_ms: int = 1000
    ) -> str | None:
        """One iteration of a worker's drain loop: reclaim stale leases,
        promote due delayed retries, then read and process one new
        message. Returns the `run_id` it touched, or `None` if there was
        nothing to do."""
        stream = self._stream_key(workflow)
        await self._ensure_group(stream)
        await self._reclaim_stale(workflow, consumer)
        await self._promote_due_delayed(workflow)

        raw = await self._redis.xreadgroup(_GROUP, consumer, {stream: ">"}, count=1, block=block_ms)
        resp = cast("list[tuple[Any, list[tuple[Any, dict[Any, Any]]]]]", raw)
        if not resp or not resp[0][1]:
            return None
        _name, entries = resp[0]
        entry_id, fields = entries[0]
        run_id = _field(fields, "run_id")
        await self._process_entry(workflow, entry_id, run_id)
        return run_id

    async def _reclaim_stale(self, workflow: str, consumer: str) -> None:
        stream = self._stream_key(workflow)
        raw = await self._redis.xautoclaim(
            stream,
            _GROUP,
            consumer,
            min_idle_time=self._visibility_timeout_ms,
            start_id="0-0",
            count=20,
        )
        _cursor, claimed, _deleted = cast("tuple[Any, list[tuple[Any, dict[Any, Any]]], Any]", raw)
        for entry_id, fields in claimed:
            run_id = _field(fields, "run_id")
            await self._process_entry(workflow, entry_id, run_id)

    async def _promote_due_delayed(self, workflow: str) -> None:
        key = self._delayed_key(workflow)
        raw_due = await self._redis.zrangebyscore(key, min=0, max=time.time())
        due = cast("list[Any]", raw_due)
        for member in due:
            run_id = _decode(member)
            await self._redis.zrem(key, str(member))
            await self._redis.xadd(self._stream_key(workflow), {"run_id": run_id})

    async def _process_entry(self, workflow: str, entry_id: Any, run_id: str) -> None:
        stream = self._stream_key(workflow)
        run = await self._run_repo.get(run_id)
        if run is None or run.status in ("succeeded", "failed"):
            await self._redis.xack(stream, _GROUP, entry_id)
            return

        outcome = await self._drive(run)
        if outcome == "crashed":
            return  # leave pending -- a real crash never gets to ack either
        if outcome == "failed":
            await self._redis.xadd(self._dlq_key(workflow), {"run_id": run_id})
        await self._redis.xack(stream, _GROUP, entry_id)

    async def _drive(self, run: WorkflowRun) -> _DriveOutcome:
        steps = self._workflows[run.workflow]
        outputs: dict[str, Any] = {}

        for step in steps:
            record = await self._records.get(run.id, step.name)
            if record is not None and record.status == "succeeded":
                assert record.output is not None
                outputs[step.name] = record.output
                continue

            attempt = (record.attempts if record is not None else 0) + 1
            if self._fail_at is not None and self._fail_at(step.name, attempt):
                return "crashed"

            ctx = StepContext(run_id=run.id, input=run.input, outputs=outputs, attempt=attempt)
            try:
                output = await step.execute(ctx, self._records, self._clock)
            except PortError as exc:
                if exc.transient and attempt < step.max_attempts:
                    await self._records.save(
                        WorkflowStepRecord(
                            run_id=run.id,
                            name=step.name,
                            status="pending",
                            output=None,
                            attempts=attempt,
                            updated_at=self._clock.now(),
                        )
                    )
                    due = time.time() + _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    await self._redis.zadd(self._delayed_key(run.workflow), {run.id: due})
                    return "deferred"

                await self._records.save(
                    WorkflowStepRecord(
                        run_id=run.id,
                        name=step.name,
                        status="failed",
                        output=None,
                        attempts=attempt,
                        updated_at=self._clock.now(),
                    )
                )
                await self._fail_run(run, step.name, str(exc))
                return "failed"
            else:
                outputs[step.name] = output

        await self._succeed_run(run)
        return "succeeded"

    async def _fail_run(self, run: WorkflowRun, step_name: str, error: str) -> None:
        failed = replace(
            run, status="failed", error=f"{step_name}: {error}", updated_at=self._clock.now()
        )
        await self._run_repo.update(failed)

    async def _succeed_run(self, run: WorkflowRun) -> None:
        succeeded = replace(run, status="succeeded", updated_at=self._clock.now())
        await self._run_repo.update(succeeded)


def _build(
    settings: Settings,
    *,
    workflows: Mapping[str, Sequence[BaseStep]],
    run_repo: RunRepository,
    records: StepRecordStore,
    clock: Clock,
    ids: IdGenerator,
    redis: Redis | None = None,
    fail_at: FailHook | None = None,
) -> WorkflowEngine:
    client = redis
    if client is None:
        from redis.asyncio import from_url

        client = from_url(settings.redis_url, decode_responses=True)
    return RedisStreamsWorkflowEngine(
        workflows,
        redis=client,
        run_repo=run_repo,
        records=records,
        clock=clock,
        ids=ids,
        visibility_timeout_seconds=settings.workflow_visibility_timeout_seconds,
        fail_at=fail_at,
    )


register(ProviderSpec(kind="workflow", name="redis", build=_build, label="Redis Streams"))
