"""The step template (PRD §5.2): `execute()` is written once, here, and no
step overrides it -- this is where determinism is enforced for every step,
forever.

`StepRecordStore` is an adapter-level abstraction (not a `packages/core`
port): both engines checkpoint through it, `inline` against an in-memory
store in tests and a SQL-backed one in local dev, `redis_streams` against
the SQL-backed one only. It exists here, not in `persistence/`, because a
workflow step record is workflow machinery, not a general repository.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from interviewer_core.domain.entities import WorkflowStepRecord
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.workflow import StepContext


class StepRecordStore(Protocol):
    async def get(self, run_id: str, name: str) -> WorkflowStepRecord | None: ...
    async def save(self, record: WorkflowStepRecord) -> None: ...


class InMemoryStepRecordStore:
    """Dict-backed twin of the SQL step-record store -- what the fast
    contract suite and every other lane's unit tests run on."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], WorkflowStepRecord] = {}

    async def get(self, run_id: str, name: str) -> WorkflowStepRecord | None:
        return self._records.get((run_id, name))

    async def save(self, record: WorkflowStepRecord) -> None:
        self._records[(record.run_id, record.name)] = record


class BaseStep:
    """A step author writes only `run()`. `execute()` is the template
    method: memoized lookup, run, checkpoint -- in that order, always."""

    name: str
    max_attempts: int = 3

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        raise NotImplementedError

    async def execute(
        self, ctx: StepContext, records: StepRecordStore, clock: Clock
    ) -> Mapping[str, Any]:
        record = await records.get(ctx.run_id, self.name)
        if record is not None and record.status == "succeeded":
            assert record.output is not None
            return record.output

        attempts = (record.attempts if record is not None else 0) + 1
        output = await self.run(replace(ctx, attempt=attempts))
        await records.save(
            WorkflowStepRecord(
                run_id=ctx.run_id,
                name=self.name,
                status="succeeded",
                output=dict(output),
                attempts=attempts,
                updated_at=clock.now(),
            )
        )
        return output


@dataclass(frozen=True)
class SimulatedCrash(Exception):
    """Raised by `inline.py`'s injectable `fail_at` hook to model a process
    dying mid-run: nothing about this step is checkpointed, the same way a
    real `kill -9` would leave nothing written past the last committed
    checkpoint. A test "restarts" by calling `start()` again."""

    step: str
    attempt: int

    def __str__(self) -> str:
        return f"simulated crash at step {self.step!r}, attempt {self.attempt}"
