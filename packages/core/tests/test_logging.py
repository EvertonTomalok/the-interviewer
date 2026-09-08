from __future__ import annotations

import logging

import pytest

from interviewer_core.logging import JsonFormatter, KeyValueFormatter


def _record_with_context(context: dict[str, object]) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="something happened",
        args=(),
        exc_info=None,
    )
    record.context = context  # type: ignore[attr-defined]
    return record


@pytest.mark.parametrize(
    "key",
    ["authorization", "api_key", "passkey", "llm_api_key", "session_token"],
)
def test_json_formatter_redacts_secret_keys(key: str) -> None:
    record = _record_with_context({key: "super-secret-value"})
    output = JsonFormatter().format(record)
    assert "super-secret-value" not in output


@pytest.mark.parametrize(
    "key",
    ["authorization", "api_key", "passkey", "llm_api_key", "session_token"],
)
def test_keyvalue_formatter_redacts_secret_keys(key: str) -> None:
    record = _record_with_context({key: "super-secret-value"})
    output = KeyValueFormatter().format(record)
    assert "super-secret-value" not in output


def test_non_secret_context_passes_through() -> None:
    record = _record_with_context({"session_id": "abc123"})
    output = JsonFormatter().format(record)
    assert "abc123" in output
