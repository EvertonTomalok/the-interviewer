"""`IdGenerator` as a port. Both implementations are pure stdlib."""

from __future__ import annotations

import os
import time
from typing import Protocol
from uuid import UUID


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class Uuid7Ids:
    """RFC 9562 UUIDv7: a 48-bit millisecond timestamp plus random bits.

    Time-ordered ids sort the way they were created -- useful for anything
    keyed by insertion order without a separate `created_at` index.
    """

    def new_id(self) -> str:
        millis = time.time_ns() // 1_000_000
        time_bytes = millis.to_bytes(6, "big")
        rand = bytearray(os.urandom(10))
        rand[0] = (rand[0] & 0x0F) | 0x70  # version 7
        rand[2] = (rand[2] & 0x3F) | 0x80  # RFC 4122 variant
        return str(UUID(bytes=bytes(time_bytes) + bytes(rand)))


class SeqIds:
    """Test double: deterministic, sequential, prefixed ids."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n}"
