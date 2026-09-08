"""`Clock` as a port: "now" is a value the workflow reads, not a side effect.

Both implementations are pure stdlib, so both ship here rather than behind
an adapter -- there is no credential, no transport, nothing to swap for a
provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FrozenClock:
    """Test double: `now()` returns a fixed instant until `advance()` moves it."""

    _now: datetime

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now = self._now + timedelta(**kwargs)
