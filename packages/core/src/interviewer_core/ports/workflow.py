"""The durable-workflow port (PRD §5.2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class StepContext:
    run_id: str
    input: Mapping[str, Any]
    outputs: Mapping[str, Any]
    attempt: int


class WorkflowStep(Protocol):
    name: str
    max_attempts: int

    async def run(self, ctx: StepContext) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RunHandle:
    run_id: str


@dataclass(frozen=True)
class RunState:
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    error: str | None = None
    outputs: Mapping[str, Any] = field(default_factory=dict)


class WorkflowEngine(Protocol):
    async def start(
        self,
        workflow: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> RunHandle:
        """Idempotent: the same key returns the same run, never a second one."""
        ...

    async def status(self, run_id: str) -> RunState: ...

    async def cancel(self, run_id: str) -> None: ...
