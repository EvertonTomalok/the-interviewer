"""`STT_PROVIDER=fake`: real, registered, refused in prod -- same story as
the LLM fake."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError
from interviewer_core.ports.speech import SpeechToTextPort, Transcript
from interviewer_core.registry import ProviderSpec, register


@dataclass
class FakeSTT:
    async def transcribe(
        self, audio: bytes, *, mime: str, language: str | None = None
    ) -> Transcript:
        digest = hashlib.sha256(audio).hexdigest()[:8]
        return Transcript(text=f"[fake transcript {digest}]", language=language)


def _build(settings: Settings) -> SpeechToTextPort:
    if settings.app_env == "prod":
        raise ConfigError("STT_PROVIDER=fake is refused when APP_ENV=prod")
    return FakeSTT()


register(ProviderSpec(kind="stt", name="fake", build=_build, label="Scripted (dev only)"))
