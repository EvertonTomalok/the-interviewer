from __future__ import annotations

import asyncio

import pytest

from interviewer_worker.__main__ import main


async def test_main_starts_logs_and_blocks_until_cancelled() -> None:
    task = asyncio.create_task(main())
    await asyncio.sleep(0.05)
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
