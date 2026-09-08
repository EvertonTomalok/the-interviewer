from __future__ import annotations

from interviewer_adapters.speech import (  # noqa: F401  -- registers providers
    fake_stt,
    stt_openai_compat,
    stt_openrouter,
    tts_none,
    tts_openai_compat,
)
from interviewer_adapters.speech.boundary import validate_upload
from interviewer_adapters.speech.fake_tts import FakeTTS

__all__ = ["FakeTTS", "validate_upload"]
