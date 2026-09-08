from __future__ import annotations

import httpx
import pytest
import respx

from interviewer_adapters.speech.stt_openai_compat import OpenAICompatSTT, _build
from interviewer_core.config import ProviderCreds, Settings, SpeechCreds
from interviewer_core.errors import ConfigError, PortError

_BASE_URL = "https://speech.example.com/v1"
_URL = f"{_BASE_URL}/audio/transcriptions"


def _settings(**overrides: object) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
        **overrides,  # type: ignore[arg-type]
    )


@respx.mock
async def test_transcribe_success_parses_text() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"text": "hello world"}))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    transcript = await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert transcript.text == "hello world"


@respx.mock
async def test_transcribe_passes_language_hint_through_unchanged() -> None:
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json={"text": "ola"}))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    transcript = await stt.transcribe(b"audio-bytes", mime="audio/wav", language="pt")

    assert transcript.language == "pt"
    sent = route.calls[0].request.content
    assert b'name="language"' in sent
    assert b"pt" in sent


@respx.mock
async def test_transcribe_401_is_not_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is False
    assert exc_info.value.status == 401


@respx.mock
async def test_transcribe_429_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(429, text="slow down"))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is True


@respx.mock
async def test_transcribe_malformed_body_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, content=b"not json"))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is True


@respx.mock
async def test_transcribe_200_with_error_field_raises() -> None:
    respx.post(_URL).mock(
        return_value=httpx.Response(200, json={"error": {"message": "bad audio"}})
    )
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    with pytest.raises(PortError, match="bad audio"):
        await stt.transcribe(b"audio-bytes", mime="audio/wav")


@respx.mock
async def test_transcribe_unreachable_is_transient() -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectError("no route"))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is True


@respx.mock
async def test_transcribe_no_text_field_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={}))
    stt = OpenAICompatSTT(api_key="k", model="whisper-1", base_url=_BASE_URL)

    with pytest.raises(PortError, match="no transcript text"):
        await stt.transcribe(b"audio-bytes", mime="audio/wav")


def test_build_missing_api_key_raises_config_error_naming_the_var() -> None:
    settings = _settings(stt=SpeechCreds(openai_compat=ProviderCreds(base_url=_BASE_URL)))

    with pytest.raises(ConfigError, match="STT__OPENAI_COMPAT__API_KEY"):
        _build(settings)


def test_build_missing_base_url_raises_config_error_naming_the_var() -> None:
    settings = _settings(stt=SpeechCreds(openai_compat=ProviderCreds(api_key="abc")))

    with pytest.raises(ConfigError, match="STT__OPENAI_COMPAT__BASE_URL"):
        _build(settings)


def test_build_with_creds_returns_configured_port() -> None:
    settings = _settings(
        stt=SpeechCreds(openai_compat=ProviderCreds(api_key="abc", base_url=_BASE_URL)),
        stt_model="whisper-1",
    )

    stt = _build(settings)

    assert isinstance(stt, OpenAICompatSTT)
