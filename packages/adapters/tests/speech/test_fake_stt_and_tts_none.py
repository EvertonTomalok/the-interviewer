from __future__ import annotations

from types import SimpleNamespace

import pytest

from interviewer_adapters.speech.fake_stt import FakeSTT
from interviewer_adapters.speech.fake_stt import _build as build_stt
from interviewer_adapters.speech.tts_none import NoneTTS
from interviewer_adapters.speech.tts_none import _build as build_tts
from interviewer_core.errors import ConfigError


async def test_fake_stt_transcribes_something() -> None:
    stt = FakeSTT()
    transcript = await stt.transcribe(b"some audio bytes", mime="audio/wav")
    assert transcript.text.startswith("[fake transcript")


def test_fake_stt_build_refuses_in_prod() -> None:
    with pytest.raises(ConfigError, match="prod"):
        build_stt(SimpleNamespace(app_env="prod"))


async def test_none_tts_raises_naming_reply_mode_and_provider() -> None:
    tts = NoneTTS()
    with pytest.raises(ConfigError, match="REPLY_MODE") as excinfo:
        await tts.synthesize("hello", voice=None, format="wav")
    assert "TTS_PROVIDER" in str(excinfo.value)


def test_none_tts_build_allowed_in_prod() -> None:
    assert isinstance(build_tts(SimpleNamespace(app_env="prod")), NoneTTS)
