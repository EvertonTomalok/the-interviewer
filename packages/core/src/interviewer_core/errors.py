"""Small exception hierarchy the layers above catch narrowly."""

from __future__ import annotations


class ConfigError(Exception):
    """Raised at process start: a missing variable or an unknown provider slug.

    The message always names the offending variable or slug -- a config
    error a reader has to guess at defeats the point of failing loudly.
    """


class PortError(Exception):
    """What every adapter maps its transport failure onto.

    No port raises a provider-specific exception; the workflow reads
    `transient`, never a guessed HTTP status.
    """

    def __init__(self, message: str, *, transient: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.status = status


class DomainError(Exception):
    """An illegal state transition or an invalid domain construction."""
