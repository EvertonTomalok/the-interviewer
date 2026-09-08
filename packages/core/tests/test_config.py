from __future__ import annotations

import pytest

from interviewer_core.config import load_settings
from interviewer_core.errors import ConfigError


def test_missing_credential_fails_naming_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_settings()

    assert "DATABASE_URL" in str(exc_info.value)


def test_reply_mode_voice_without_tts_provider_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("REPLY_MODE", "voice")
    monkeypatch.setenv("TTS_PROVIDER", "none")

    with pytest.raises(ConfigError, match="REPLY_MODE"):
        load_settings()


def test_nested_delimiter_reaches_a_credential_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("LLM__OPENROUTER__API_KEY", "sk-test")

    settings = load_settings()

    assert settings.llm.openrouter.api_key == "sk-test"


def test_upload_allowed_mime_types_is_parsed_from_the_csv_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = load_settings()

    assert "audio/wav" in settings.upload_allowed_mime_types
