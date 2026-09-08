"""`WORKFLOW_PROVIDER=inline`: runs a workflow's steps in-process, in order,
through the same `BaseStep` objects `redis_streams` will use. This is the
test engine and the local-dev engine -- a whole interview runs on it with
no Redis at all.

Retry-with-backoff and DLQ live here, in the engine, not in `BaseStep`:
invariant 4 (PRD §5.2) says the workflow decides to retry from
`PortError.transient`, and that decision is the engine's, once, for every
step -- a step author never writes retry logic.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from interviewer_adapters.workflow.base import BaseStep, SimulatedCrash, StepRecordStore
from interviewer_core.config import Settings
from interviewer_core.domain.entities import WorkflowRun, WorkflowStepRecord
from interviewer_core.errors import PortError
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import RunRepository
from interviewer_core.ports.workflow import RunHandle, RunState, StepContext, WorkflowEngine
from interviewer_core.registry import ProviderSpec, register

#: `fail_at(step_name, attempt)` -- `True` simulates a crash before that
#: step's `run()` is even called, so nothing about it gets checkpointed.
FailHook = Callable[[str, int], bool]

_BASE_BACKOFF_SECONDS = 0.01
_MAX_JITTER_SECONDS = 0.01


class InlineWorkflowEngine:
    """Satisfies `WorkflowEngine`, driving every registered workflow's steps
    in-process. Two workflows, `turn` and `evaluation`, run through the
    exact same engine -- there is no special-casing per workflow name."""

    def __init__(
        self,
        workflows: Mapping[str, Sequence[BaseStep]],
        *,
        run_repo: RunRepository,
        records: StepRecordStore,
        clock: Clock,
        ids: IdGenerator,
        fail_at: FailHook | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._workflows = workflows
        self._run_repo = run_repo
        self._records = records
        self._clock = clock
        self._ids = ids
        self._fail_at = fail_at
        self._sleep = sleep

    def set_fail_at(self, fail_at: FailHook | None) -> None:
        """Swap the crash-injection hook -- a test "restarts" by clearing it
        and calling `start()` again with the same `idempotency_key`."""
        self._fail_at = fail_at

    def set_workflow(self, workflow: str, steps: Sequence[BaseStep]) -> None:
        """Replace one workflow's steps -- lets a test swap in a step built
        against a differently-wired port without reconstructing the engine."""
        self._workflows = {**self._workflows, workflow: steps}

    async def start(
        self,
        workflow: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> RunHandle:
        existing = await self._run_repo.get_by_idempotency_key(idempotency_key)
        run = (
            existing
            if existing is not None
            else await self._create_run(workflow, payload, idempotency_key)
        )

        if run.status in ("succeeded", "failed"):
            return RunHandle(run_id=run.id)

        await self._drive(run)
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

    async def _drive(self, run: WorkflowRun) -> None:
        steps = self._workflows[run.workflow]
        outputs: dict[str, Any] = {}

        for step in steps:
            record = await self._records.get(run.id, step.name)
            if record is not None and record.status == "succeeded":
                assert record.output is not None
                outputs[step.name] = record.output
                continue

            attempt = record.attempts if record is not None else 0
            while True:
                attempt += 1
                if self._fail_at is not None and self._fail_at(step.name, attempt):
                    raise SimulatedCrash(step.name, attempt)

                ctx = StepContext(run_id=run.id, input=run.input, outputs=outputs, attempt=attempt)
                try:
                    output = await step.execute(ctx, self._records, self._clock)
                except PortError as exc:
                    if exc.transient and attempt < step.max_attempts:
                        await self._sleep(
                            _BASE_BACKOFF_SECONDS * attempt + random.uniform(0, _MAX_JITTER_SECONDS)
                        )
                        continue
                    await self._fail_step_and_run(run, step.name, attempt, str(exc))
                    raise
                except Exception as exc:  # noqa: BLE001 -- a step's own bug or bad data is a
                    # permanent failure of this run, classified like a non-transient
                    # PortError; it must still mark the run failed (never leave it
                    # stuck at "running" forever) before propagating -- see ADR 0004's
                    # neighbor incident on the redis_streams side of this same fix.
                    await self._fail_step_and_run(run, step.name, attempt, str(exc))
                    raise
                else:
                    outputs[step.name] = output
                    break

        await self._succeed_run(run)

    async def _fail_step_and_run(
        self, run: WorkflowRun, step_name: str, attempt: int, error: str
    ) -> None:
        await self._records.save(
            WorkflowStepRecord(
                run_id=run.id,
                name=step_name,
                status="failed",
                output=None,
                attempts=attempt,
                updated_at=self._clock.now(),
            )
        )
        await self._fail_run(run, step_name, error)

    async def _fail_run(self, run: WorkflowRun, step_name: str, error: str) -> None:
        failed = replace(
            run, status="failed", error=f"{step_name}: {error}", updated_at=self._clock.now()
        )
        await self._run_repo.update(failed)

    async def _succeed_run(self, run: WorkflowRun) -> None:
        succeeded = replace(run, status="succeeded", updated_at=self._clock.now())
        await self._run_repo.update(succeeded)

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


def _build(
    settings: Settings,
    *,
    workflows: Mapping[str, Sequence[BaseStep]],
    run_repo: RunRepository,
    records: StepRecordStore,
    clock: Clock,
    ids: IdGenerator,
    fail_at: FailHook | None = None,
) -> WorkflowEngine:
    return InlineWorkflowEngine(
        workflows, run_repo=run_repo, records=records, clock=clock, ids=ids, fail_at=fail_at
    )


register(ProviderSpec(kind="workflow", name="inline", build=_build, label="In-process (dev/test)"))
