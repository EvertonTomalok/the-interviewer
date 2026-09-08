"""Transcription over OpenRouter -- audio as chat input, not its own endpoint.

OpenRouter has no `/audio/transcriptions`; what it has is `input_audio` on
`/chat/completions`, against multimodal models such as `google/gemini-2.5-flash`.
`stt_openai_compat` posts the whisper-shaped multipart request instead, which
is why pointing it at OpenRouter fails with "model does not exist" -- wrong
endpoint entirely, not a bad model name.
"""

from __future__ import annotations

import base64

import httpx

from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.speech import SpeechToTextPort, Transcript
from interviewer_core.registry import ProviderSpec, register

TRANSIENT_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})

SYSTEM_PROMPT = (
    "You transcribe a job candidate's spoken answer in an interview. "
    "Return the literal transcript, with punctuation. Do not summarize, "
    "comment, translate, or add anything that was not said. If the audio "
    "is empty or inaudible, respond with exactly: [inaudible]"
)

USER_PROMPT = "Transcribe this audio."

_FORMATS: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/flac": "flac",
}


def _audio_format(mime: str) -> str:
    base = mime.split(";", 1)[0].strip().lower()
    return _FORMATS.get(base, "webm")


class OpenRouterSTT:
    """Satisfies `SpeechToTextPort` against OpenRouter's `/chat/completions`."""

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
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(audio).decode("ascii"),
                                "format": _audio_format(mime),
                            },
                        },
                    ],
                },
            ],
            "temperature": 0.0,
        }
        body = await self._post(payload)

        if body.get("error"):
            raise PortError(
                f"stt openrouter returned an error body: {str(body['error'])[:400]}",
                transient=True,
            )

        text = _content(body)
        if not text:
            raise PortError("stt openrouter returned no transcript text", transient=True)

        return Transcript(text=text, language=language)

    async def _post(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise PortError(f"stt openrouter timed out: {exc}", transient=True) from exc
        except httpx.HTTPError as exc:
            raise PortError(f"stt openrouter unreachable: {exc}", transient=True) from exc

        if response.status_code >= 400:
            raise PortError(
                f"stt openrouter returned HTTP {response.status_code}: {response.text[:400]}",
                transient=response.status_code in TRANSIENT_STATUSES,
                status=response.status_code,
            )
        try:
            body: dict[str, object] = response.json()
        except ValueError as exc:
            raise PortError("stt openrouter returned a non-JSON body", transient=True) from exc
        return body


def _content(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(part.get("text") or "") for part in content if isinstance(part, dict)]
        return "".join(parts).strip()
    return ""


def _build(settings: Settings) -> SpeechToTextPort:
    creds = settings.stt.openrouter
    if not creds.api_key:
        raise ConfigError("missing STT__OPENROUTER__API_KEY")
    return OpenRouterSTT(
        api_key=creds.api_key,
        model=settings.stt_model,
        base_url=creds.base_url or "https://openrouter.ai/api/v1",
    )


register(ProviderSpec(kind="stt", name="openrouter", build=_build, label="OpenRouter"))
