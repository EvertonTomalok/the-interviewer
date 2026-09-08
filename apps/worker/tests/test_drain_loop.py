"""`_drain_loop` against a stubbed engine: idle-and-wait when the provider
has no `consume_once` (`WORKFLOW_PROVIDER=inline`), and draining both
workflows by name, stopping cleanly on shutdown, when it does."""

from __future__ import annotations

import asyncio
from typing import Any

from interviewer_worker import deps
from interviewer_worker.__main__ import _drain_loop


class _NoConsumeEngine:
    """Stands in for `InlineWorkflowEngine`: no `consume_once` at all."""


async def test_a_provider_with_no_consume_once_just_waits_for_shutdown(monkeypatch: Any) -> None:
    monkeypatch.setattr(deps, "get_workflow_engine", lambda: _NoConsumeEngine())

    stop = asyncio.Event()
    task = asyncio.create_task(_drain_loop(stop))
    await asyncio.sleep(0.01)
    assert not task.done()  # idling, not looping, not raising

    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()


class _StubStreamEngine:
    """A minimal stand-in for `RedisStreamsWorkflowEngine`: only
    `consume_once` exists, exactly what `_drain_loop` duck-types on."""

    def __init__(self, run_ids: list[str | None]) -> None:
        self._run_ids = run_ids
        self.calls: list[tuple[str, str]] = []

    async def consume_once(self, workflow: str, *, consumer: str, block_ms: int) -> str | None:
        # A real `block_ms` blocks on the network long enough to yield the
        # event loop fairly; resolving instantly here would let the drain
        # loop's tight `while` starve the test's own `stop.set()` timer.
        await asyncio.sleep(0)
        self.calls.append((workflow, consumer))
        if self._run_ids:
            return self._run_ids.pop(0)
        return None


async def test_it_drains_both_workflows_by_name_and_stops_on_shutdown(monkeypatch: Any) -> None:
    engine = _StubStreamEngine(["run-1", None, "run-2"])
    monkeypatch.setattr(deps, "get_workflow_engine", lambda: engine)

    stop = asyncio.Event()
    task = asyncio.create_task(_drain_loop(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)

    workflows_touched = {call[0] for call in engine.calls}
    assert workflows_touched == {"turn", "evaluation"}
