from __future__ import annotations

import httpx
import pytest
import respx

from interviewer_adapters.speech.tts_openai_compat import OpenAICompatTTS, _build
from interviewer_core.config import ProviderCreds, Settings, SpeechCreds
from interviewer_core.errors import ConfigError, PortError

_BASE_URL = "https://speech.example.com/v1"
_URL = f"{_BASE_URL}/audio/speech"


def _settings(**overrides: object) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
        **overrides,  # type: ignore[arg-type]
    )


@respx.mock
async def test_synthesize_success_returns_bytes_and_mime() -> None:
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200, content=b"fake-mp3-bytes", headers={"content-type": "audio/mpeg"}
        )
    )
    tts = OpenAICompatTTS(api_key="k", model="tts-1", base_url=_BASE_URL)

    blob = await tts.synthesize("hello", voice="alloy", format="mp3")

    assert blob.content == b"fake-mp3-bytes"
    assert blob.mime == "audio/mpeg"


@respx.mock
async def test_synthesize_falls_back_to_format_mime_without_header() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, content=b"bytes"))
    tts = OpenAICompatTTS(api_key="k", model="tts-1", base_url=_BASE_URL)

    blob = await tts.synthesize("hello", voice=None, format="wav")

    assert blob.mime == "audio/wav"


@respx.mock
async def test_synthesize_401_is_not_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    tts = OpenAICompatTTS(api_key="k", model="tts-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await tts.synthesize("hello", voice=None, format="mp3")

    assert exc_info.value.transient is False
    assert exc_info.value.status == 401


@respx.mock
async def test_synthesize_429_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(429, text="slow down"))
    tts = OpenAICompatTTS(api_key="k", model="tts-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await tts.synthesize("hello", voice=None, format="mp3")

    assert exc_info.value.transient is True


@respx.mock
async def test_synthesize_empty_body_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, content=b""))
    tts = OpenAICompatTTS(api_key="k", model="tts-1", base_url=_BASE_URL)

    with pytest.raises(PortError, match="no audio"):
        await tts.synthesize("hello", voice=None, format="mp3")


@respx.mock
async def test_synthesize_unreachable_is_transient() -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectError("no route"))
    tts = OpenAICompatTTS(api_key="k", model="tts-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await tts.synthesize("hello", voice=None, format="mp3")

    assert exc_info.value.transient is True


def test_build_missing_api_key_raises_config_error_naming_the_var() -> None:
    settings = _settings(tts=SpeechCreds(openai_compat=ProviderCreds(base_url=_BASE_URL)))

    with pytest.raises(ConfigError, match="TTS__OPENAI_COMPAT__API_KEY"):
        _build(settings)


def test_build_missing_base_url_raises_config_error_naming_the_var() -> None:
    settings = _settings(tts=SpeechCreds(openai_compat=ProviderCreds(api_key="abc")))

    with pytest.raises(ConfigError, match="TTS__OPENAI_COMPAT__BASE_URL"):
        _build(settings)


def test_build_with_creds_returns_configured_port() -> None:
    settings = _settings(
        tts=SpeechCreds(openai_compat=ProviderCreds(api_key="abc", base_url=_BASE_URL)),
        tts_model="tts-1",
    )

    tts = _build(settings)

    assert isinstance(tts, OpenAICompatTTS)
