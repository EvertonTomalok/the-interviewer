"""`TTS_PROVIDER=none`: the Null Object, and the PoC default.

`REPLY_MODE=text` skips the `synthesize` workflow step entirely; this
adapter exists so the port has a total implementation even when nothing
should call it. It is not a "fake" -- it is never refused in prod, because
the PoC's real, intended shape is text replies.
"""

from __future__ import annotations

from dataclasses import dataclass

from interviewer_core.config import Settings
from interviewer_core.ports.speech import AudioBlob, TextToSpeechPort
from interviewer_core.registry import ProviderSpec, register


@dataclass
class NoneTTS:
    async def synthesize(self, text: str, *, voice: str | None, format: str) -> AudioBlob:
        return AudioBlob(content=b"", mime="audio/none")


def _build(settings: Settings) -> TextToSpeechPort:
    return NoneTTS()


register(ProviderSpec(kind="tts", name="none", build=_build, label="No speech (text replies)"))
