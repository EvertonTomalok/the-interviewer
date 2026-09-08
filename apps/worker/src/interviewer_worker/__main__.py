"""Worker process entrypoint: drains the durable workflow through the
`WorkflowEngine` adapter -- claim, run the step, checkpoint, ack. Both
workflows, `turn` and `evaluation`, are drained by the same loop; this
module knows their names, never what they mean.

`WORKFLOW_PROVIDER=inline` needs no separate consumer at all -- the engine
already drove every run to completion inside the API's own request
(`interviewer_api.deps.spawn`), so this process just stays up for
`docker compose`'s health check and exits cleanly on shutdown. Only
`WORKFLOW_PROVIDER=redis` actually has a stream to drain, through
`RedisStreamsWorkflowEngine.consume_once` -- duck-typed, not imported by
name, so this module never has to know which provider it got.
"""

from __future__ import annotations

import asyncio
import signal
import socket
import uuid
from typing import Any, Protocol

from interviewer_core.logging import configure_logging, get_logger
from interviewer_worker import deps

logger = get_logger("interviewer_worker")

#: Both durable workflows this product has. A worker knows their names, not
#: what a step inside either one does.
_WORKFLOWS = ("turn", "evaluation")


class _ConsumeOnce(Protocol):
    """The shape of a bound `RedisStreamsWorkflowEngine.consume_once` --
    typed as a callable, not as an object, because that is what `getattr`
    below actually returns."""

    async def __call__(self, workflow: str, *, consumer: str, block_ms: int) -> str | None: ...


async def _drain_loop(stop: asyncio.Event) -> None:
    engine: Any = deps.get_workflow_engine()
    consume: _ConsumeOnce | None = getattr(engine, "consume_once", None)
    if consume is None:
        logger.info("worker_idle", reason="workflow_provider drives inline, nothing to consume")
        await stop.wait()
        return

    consumer_name = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    logger.info("worker_started", consumer=consumer_name, workflows=_WORKFLOWS)
    while not stop.is_set():
        for workflow in _WORKFLOWS:
            run_id = await consume(workflow, consumer=consumer_name, block_ms=1000)
            if run_id is not None:
                logger.info("run_processed", workflow=workflow, run_id=run_id)


async def main() -> None:
    settings = deps.get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    drain = asyncio.create_task(_drain_loop(stop))
    await drain
    # Graceful shutdown: a `consume_once` already in flight (blocked up to
    # its own `block_ms`) finishes its current step and checkpoints before
    # the loop above re-checks `stop` and returns -- the visibility timeout
    # is what covers a hard kill, never a normal stop.
    logger.info("worker_shutting_down")


if __name__ == "__main__":
    asyncio.run(main())
