"""Worker process entrypoint.

Placeholder until T07 (workflow adapters) and T09 (worker wiring) land: it
starts, logs once, and blocks on shutdown signals so the container stays up
under `docker compose --profile app up`. The real consumer loop replaces the
body of `main()`, not this module's shape.
"""

from __future__ import annotations

import asyncio
import logging
import signal

logger = logging.getLogger("interviewer_worker")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("worker started (no workflow adapter wired yet)")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    logger.info("worker shutting down")


if __name__ == "__main__":
    asyncio.run(main())
