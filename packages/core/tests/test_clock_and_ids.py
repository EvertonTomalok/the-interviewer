from __future__ import annotations

from datetime import UTC, datetime, timedelta

from interviewer_core.ports.clock import FrozenClock, SystemClock
from interviewer_core.ports.ids import SeqIds, Uuid7Ids


def test_system_clock_returns_a_timezone_aware_now() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None


def test_frozen_clock_stays_fixed_until_advanced() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(start)
    assert clock.now() == start

    clock.advance(hours=1)
    assert clock.now() == start + timedelta(hours=1)


def test_seq_ids_are_deterministic_and_prefixed() -> None:
    ids = SeqIds(prefix="session")
    assert ids.new_id() == "session-1"
    assert ids.new_id() == "session-2"


def test_uuid7_ids_are_unique_and_well_formed() -> None:
    ids = Uuid7Ids()
    first = ids.new_id()
    second = ids.new_id()
    assert first != second
    assert len(first) == 36
    assert first[14] == "7"  # version nibble
