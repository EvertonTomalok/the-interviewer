from __future__ import annotations

import asyncio
from typing import Any

import pytest

from interviewer_core.config import Settings
from interviewer_worker import deps
from interviewer_worker.__main__ import main


class _IdleEngine:
    """No `consume_once` -- `main()` idles under this the same way it does
    for `WORKFLOW_PROVIDER=inline`, without needing a real database."""


async def test_main_starts_logs_and_blocks_until_cancelled(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(database_url="postgresql+asyncpg://test/test", redis_url="redis://test"),
    )
    monkeypatch.setattr(deps, "get_workflow_engine", lambda: _IdleEngine())

    task = asyncio.create_task(main())
    await asyncio.sleep(0.05)
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
