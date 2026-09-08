from __future__ import annotations

from interviewer_adapters.speech.fake_tts import FakeTTS


async def test_fake_tts_returns_a_wav_a_player_accepts() -> None:
    tts = FakeTTS()

    blob = await tts.synthesize("hello there", voice=None, format="wav")

    assert blob.mime == "audio/wav"
    assert blob.content[:4] == b"RIFF"
    assert blob.content[8:12] == b"WAVE"


async def test_fake_tts_length_scales_with_text() -> None:
    tts = FakeTTS()

    short = await tts.synthesize("hi", voice=None, format="wav")
    long = await tts.synthesize("hi " * 200, voice=None, format="wav")

    assert len(long.content) > len(short.content)
