#!/usr/bin/env python3
"""`make dev` -- API with --reload and the worker, on the host, one Ctrl-C.

Runs both processes as children and forwards SIGINT/SIGTERM to both, so one
Ctrl-C stops the whole loop instead of leaving the worker orphaned.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from types import FrameType

PROCS: list[subprocess.Popen[bytes]] = []
STOPPING = False


def _stop_all(_signum: int, _frame: FrameType | None) -> None:
    global STOPPING
    STOPPING = True
    for proc in PROCS:
        if proc.poll() is None:
            proc.terminate()


def main() -> int:
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "interviewer_api.main:app",
            "--reload",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]
    )
    worker = subprocess.Popen([sys.executable, "-m", "interviewer_worker"])
    PROCS.extend([api, worker])

    signal.signal(signal.SIGINT, _stop_all)
    signal.signal(signal.SIGTERM, _stop_all)

    exit_code = 0
    while not STOPPING:
        for proc in PROCS:
            code = proc.poll()
            if code is not None:
                exit_code = code
                _stop_all(signal.SIGTERM, None)
                break
        time.sleep(0.2)

    for proc in PROCS:
        proc.wait()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
