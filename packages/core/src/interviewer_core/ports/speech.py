from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None


class SpeechToTextPort(Protocol):
    async def transcribe(
        self, audio: bytes, *, mime: str, language: str | None = None
    ) -> Transcript: ...


@dataclass(frozen=True)
class AudioBlob:
    content: bytes
    mime: str


class TextToSpeechPort(Protocol):
    async def synthesize(self, text: str, *, voice: str | None, format: str) -> AudioBlob: ...
