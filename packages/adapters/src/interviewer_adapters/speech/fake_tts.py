"""`FakeTTS`: a test double, not a registered provider.

The only configured way to have no voice output is `TTS_PROVIDER=none`
(`tts_none.py`) -- `FakeTTS` exists so a voice-mode test can inject a real,
playable WAV without a network call, the way `FakeLLM`/`FakeSTT` stand in
for their own ports. It is never selected by a slug.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from interviewer_core.ports.speech import AudioBlob

_SAMPLE_RATE = 16_000
_MIN_SECONDS = 0.5
_SECONDS_PER_CHAR = 0.05


@dataclass
class FakeTTS:
    async def synthesize(self, text: str, *, voice: str | None, format: str) -> AudioBlob:
        seconds = max(_MIN_SECONDS, len(text) * _SECONDS_PER_CHAR)
        frame_count = int(_SAMPLE_RATE * seconds)
        return AudioBlob(content=_silent_wav(frame_count), mime="audio/wav")


def _silent_wav(frame_count: int) -> bytes:
    """A minimal, valid 16-bit mono PCM WAV of `frame_count` silent samples."""
    data = b"\x00\x00" * frame_count
    byte_rate = _SAMPLE_RATE * 2
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, _SAMPLE_RATE, byte_rate, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    return header + data
