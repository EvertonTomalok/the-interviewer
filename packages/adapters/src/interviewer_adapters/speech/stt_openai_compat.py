"""Adapter for a whisper-shaped `/audio/transcriptions` endpoint.

The one speech call the PoC makes against a real provider (PRD §2): the
candidate speaks, this adapter writes it down. It transcribes; it never
translates -- `language` is a hint passed straight through to the provider,
and no translate route is ever selected, because a transcript in a language
the session did not pin is a silently different product.
"""

from __future__ import annotations

import httpx

from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.speech import SpeechToTextPort, Transcript
from interviewer_core.registry import ProviderSpec, register

TRANSIENT_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


class OpenAICompatSTT:
    """Satisfies `SpeechToTextPort` against any whisper-shaped endpoint."""

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

    async def transcribe(
        self, audio: bytes, *, mime: str, language: str | None = None
    ) -> Transcript:
        data: dict[str, str] = {"model": self._model}
        if language:
            data["language"] = language
        body = await self._post(data=data, files={"file": ("audio", audio, mime)})

        if body.get("error"):
            raise PortError(
                f"stt openai_compat returned an error body: {str(body['error'])[:400]}",
                transient=True,
            )

        text = body.get("text")
        if not isinstance(text, str):
            raise PortError("stt openai_compat returned no transcript text", transient=True)

        return Transcript(text=text, language=language)

    async def _post(
        self, *, data: dict[str, str], files: dict[str, tuple[str, bytes, str]]
    ) -> dict[str, object]:
        try:
            response = await self._client.post(
                f"{self._base_url}/audio/transcriptions",
                data=data,
                files=files,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise PortError(f"stt openai_compat timed out: {exc}", transient=True) from exc
        except httpx.HTTPError as exc:
            raise PortError(f"stt openai_compat unreachable: {exc}", transient=True) from exc

        if response.status_code >= 400:
            raise PortError(
                f"stt openai_compat returned HTTP {response.status_code}: {response.text[:400]}",
                transient=response.status_code in TRANSIENT_STATUSES,
                status=response.status_code,
            )
        try:
            body: dict[str, object] = response.json()
        except ValueError as exc:
            raise PortError("stt openai_compat returned a non-JSON body", transient=True) from exc
        return body


def _build(settings: Settings) -> SpeechToTextPort:
    creds = settings.stt.openai_compat
    if not creds.api_key:
        raise ConfigError("missing STT__OPENAI_COMPAT__API_KEY")
    if not creds.base_url:
        raise ConfigError("missing STT__OPENAI_COMPAT__BASE_URL")
    return OpenAICompatSTT(api_key=creds.api_key, model=settings.stt_model, base_url=creds.base_url)


register(ProviderSpec(kind="stt", name="openai_compat", build=_build, label="OpenAI-compatible"))
