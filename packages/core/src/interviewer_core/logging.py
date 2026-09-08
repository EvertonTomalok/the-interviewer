"""Structured, redacted logging on the standard library.

See `docs/adr/0002-core-logging-without-structlog.md`: this module gives
callers the ergonomics of a structured logger (`bind`, JSON in production,
key-value in dev) without a dependency beyond the standard library.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_REDACTED = "***"
_EXACT_REDACTED_KEYS = {"authorization", "api_key", "passkey"}
_REDACTED_SUFFIXES = ("_key", "_token")


def _should_redact(key: str) -> bool:
    lowered = key.lower()
    return lowered in _EXACT_REDACTED_KEYS or lowered.endswith(_REDACTED_SUFFIXES)


def redact(context: dict[str, Any]) -> dict[str, Any]:
    return {k: (_REDACTED if _should_redact(k) else v) for k, v in context.items()}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = redact(getattr(record, "context", {}))
        payload = {"level": record.levelname, "event": record.getMessage(), **context}
        return json.dumps(payload, default=str)


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = redact(getattr(record, "context", {}))
        kv = " ".join(f"{k}={value!r}" for k, value in context.items())
        base = f"{record.levelname} {record.getMessage()}"
        return f"{base} {kv}".rstrip()


class BoundLogger:
    """A logger that carries bound context on every call, structlog-style."""

    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None) -> None:
        self._logger = logger
        self._context = context or {}

    def bind(self, **kwargs: Any) -> BoundLogger:
        return BoundLogger(self._logger, {**self._context, **kwargs})

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        context = {**self._context, **kwargs}
        self._logger.log(level, event, extra={"context": context})

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, **kwargs)


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else KeyValueFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> BoundLogger:
    return BoundLogger(logging.getLogger(name))
