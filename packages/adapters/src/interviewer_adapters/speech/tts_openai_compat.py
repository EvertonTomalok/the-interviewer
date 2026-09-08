"""Adapter for an OpenAI-shaped `/audio/speech` endpoint.

Built and fully tested in this lane, but `.env.example` ships no key for it:
`TTS_PROVIDER=none` stays the PoC default (`tts_none.py`), so this adapter
only reaches production when `REPLY_MODE=voice` flips it on. Building it now
and switching it off is what makes voice mode a flag later instead of a
project.
"""

from __future__ import annotations

import httpx

from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.speech import AudioBlob, TextToSpeechPort
from interviewer_core.registry import ProviderSpec, register

TRANSIENT_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})

_FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


class OpenAICompatTTS:
    """Satisfies `TextToSpeechPort` against any OpenAI-shaped `/audio/speech`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def synthesize(self, text: str, *, voice: str | None, format: str) -> AudioBlob:
        payload: dict[str, object] = {
            "model": self._model,
            "input": text,
            "response_format": format,
        }
        if voice:
            payload["voice"] = voice

        try:
            response = await self._client.post(
                f"{self._base_url}/audio/speech",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise PortError(f"tts openai_compat timed out: {exc}", transient=True) from exc
        except httpx.HTTPError as exc:
            raise PortError(f"tts openai_compat unreachable: {exc}", transient=True) from exc

        if response.status_code >= 400:
            raise PortError(
                f"tts openai_compat returned HTTP {response.status_code}: {response.text[:400]}",
                transient=response.status_code in TRANSIENT_STATUSES,
                status=response.status_code,
            )

        content = response.content
        if not content:
            raise PortError("tts openai_compat returned no audio", transient=True)

        mime = response.headers.get("content-type") or _FORMAT_MIME.get(format, "audio/mpeg")
        return AudioBlob(content=content, mime=mime)


def _build(settings: Settings) -> TextToSpeechPort:
    creds = settings.tts.openai_compat
    if not creds.api_key:
        raise ConfigError("missing TTS__OPENAI_COMPAT__API_KEY")
    if not creds.base_url:
        raise ConfigError("missing TTS__OPENAI_COMPAT__BASE_URL")
    return OpenAICompatTTS(api_key=creds.api_key, model=settings.tts_model, base_url=creds.base_url)


register(ProviderSpec(kind="tts", name="openai_compat", build=_build, label="OpenAI-compatible"))
