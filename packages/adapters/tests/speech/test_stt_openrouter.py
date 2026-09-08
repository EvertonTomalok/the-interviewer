from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from interviewer_adapters.speech.stt_openrouter import OpenRouterSTT, _build
from interviewer_core.config import ProviderCreds, Settings, SpeechCreds
from interviewer_core.errors import ConfigError, PortError

_BASE_URL = "https://openrouter.example.com/api/v1"
_URL = f"{_BASE_URL}/chat/completions"


def _settings(**overrides: object) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
        **overrides,  # type: ignore[arg-type]
    )


def _choice(text: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": text}}]}


@respx.mock
async def test_transcribe_success_parses_text() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_choice("hello world")))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    transcript = await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert transcript.text == "hello world"


@respx.mock
async def test_transcribe_sends_audio_as_base64_input_audio() -> None:
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_choice("ok")))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    await stt.transcribe(b"raw-audio", mime="audio/wav")

    sent = json.loads(route.calls[0].request.content)
    audio_block = sent["messages"][1]["content"][1]["input_audio"]
    assert audio_block["data"] == base64.b64encode(b"raw-audio").decode("ascii")
    assert audio_block["format"] == "wav"


@respx.mock
async def test_transcribe_keeps_language_hint_on_the_result() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_choice("ola")))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    transcript = await stt.transcribe(b"audio-bytes", mime="audio/wav", language="pt")

    assert transcript.language == "pt"


@respx.mock
async def test_transcribe_401_is_not_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is False
    assert exc_info.value.status == 401


@respx.mock
async def test_transcribe_429_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(429, text="slow down"))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is True


@respx.mock
async def test_transcribe_200_with_error_field_raises() -> None:
    respx.post(_URL).mock(
        return_value=httpx.Response(200, json={"error": {"message": "bad audio"}})
    )
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    with pytest.raises(PortError, match="bad audio"):
        await stt.transcribe(b"audio-bytes", mime="audio/wav")


@respx.mock
async def test_transcribe_no_content_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    with pytest.raises(PortError, match="no transcript text"):
        await stt.transcribe(b"audio-bytes", mime="audio/wav")


@respx.mock
async def test_transcribe_unreachable_is_transient() -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectError("no route"))
    stt = OpenRouterSTT(api_key="k", model="google/gemini-2.5-flash", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await stt.transcribe(b"audio-bytes", mime="audio/wav")

    assert exc_info.value.transient is True


def test_build_missing_api_key_raises_config_error_naming_the_var() -> None:
    settings = _settings(stt=SpeechCreds(openrouter=ProviderCreds(base_url=_BASE_URL)))

    with pytest.raises(ConfigError, match="STT__OPENROUTER__API_KEY"):
        _build(settings)


def test_build_with_creds_returns_configured_port() -> None:
    settings = _settings(
        stt=SpeechCreds(openrouter=ProviderCreds(api_key="abc", base_url=_BASE_URL)),
        stt_model="google/gemini-2.5-flash",
    )

    stt = _build(settings)

    assert isinstance(stt, OpenRouterSTT)


def test_build_defaults_base_url_when_unset() -> None:
    settings = _settings(stt=SpeechCreds(openrouter=ProviderCreds(api_key="abc")))

    stt = _build(settings)

    assert isinstance(stt, OpenRouterSTT)
