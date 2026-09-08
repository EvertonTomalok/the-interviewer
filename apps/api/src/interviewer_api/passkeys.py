"""Passkey generation and the per-slug lockout PRD §8 asks for.

`PasskeyLockout` is process-local, in-memory state -- correct for the single
API process this PoC runs, and not a shared repository because nothing in
PRD §4 models a login-attempt row. A multi-replica deployment would need
this moved behind Redis; not this task's scope.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta


def generate_passkey() -> str:
    """A short, URL-safe, high-entropy secret -- shown to the admin once."""
    return secrets.token_urlsafe(9)


@dataclass
class _SlugState:
    failures: int = 0
    locked_until: datetime | None = None


class PasskeyLockout:
    def __init__(self, *, max_attempts: int, lockout_minutes: int) -> None:
        self._max_attempts = max_attempts
        self._lockout_minutes = lockout_minutes
        self._state: dict[str, _SlugState] = {}

    def is_locked(self, slug: str, *, now: datetime) -> bool:
        state = self._state.get(slug)
        return state is not None and state.locked_until is not None and now < state.locked_until

    def record_failure(self, slug: str, *, now: datetime) -> None:
        state = self._state.setdefault(slug, _SlugState())
        state.failures += 1
        if state.failures >= self._max_attempts:
            state.locked_until = now + timedelta(minutes=self._lockout_minutes)

    def record_success(self, slug: str) -> None:
        self._state.pop(slug, None)
