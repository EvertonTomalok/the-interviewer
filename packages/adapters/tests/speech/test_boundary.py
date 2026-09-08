from __future__ import annotations

import pytest

from interviewer_adapters.speech.boundary import validate_upload
from interviewer_core.config import Settings
from interviewer_core.errors import DomainError


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
    )


def test_accepts_a_valid_upload() -> None:
    validate_upload(b"x" * 100, mime="audio/wav", settings=_settings(), duration_seconds=10.0)


def test_rejects_unsupported_mime() -> None:
    with pytest.raises(DomainError, match="mime"):
        validate_upload(b"x", mime="video/mp4", settings=_settings())


def test_rejects_oversized_upload() -> None:
    settings = _settings()
    settings.upload_max_bytes = 10
    with pytest.raises(DomainError, match="UPLOAD_MAX_BYTES"):
        validate_upload(b"x" * 11, mime="audio/wav", settings=settings)


def test_rejects_overlong_duration() -> None:
    settings = _settings()
    settings.upload_max_seconds = 5
    with pytest.raises(DomainError, match="UPLOAD_MAX_SECONDS"):
        validate_upload(b"x", mime="audio/wav", settings=settings, duration_seconds=6.0)


def test_skips_duration_check_when_not_given() -> None:
    settings = _settings()
    settings.upload_max_seconds = 1
    validate_upload(b"x", mime="audio/wav", settings=settings)
