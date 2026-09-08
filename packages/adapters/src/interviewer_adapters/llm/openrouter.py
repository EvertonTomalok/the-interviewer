"""OpenRouter chat-completions adapter over `LLMPort`.

Registers itself as `kind="llm", name="openrouter"` at import time -- see
this module's `_build` and `interviewer_adapters/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMPort, LLMUsage
from interviewer_core.registry import ProviderSpec, register

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

#: Worth retrying. Everything else is a payload or a permission problem, and
#: repeating it buys the same refusal at the same price.
TRANSIENT_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


class OpenRouterLLM:
    """Satisfies `LLMPort` against OpenRouter's `/chat/completions`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMAnswer:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = await self._post(payload)

        if body.get("error"):
            raise PortError(
                f"openrouter returned an error body: {str(body['error'])[:400]}",
                transient=True,
            )

        content = _content(body)
        if content is None:
            raise PortError("openrouter returned no content", transient=True)

        return LLMAnswer(text=content, usage=_usage(body))

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://github.com/the-interviewer",
                    "X-Title": "the-interviewer",
                },
            )
        except httpx.TimeoutException as exc:
            raise PortError(f"openrouter timed out: {exc}", transient=True) from exc
        except httpx.HTTPError as exc:
            raise PortError(f"openrouter unreachable: {exc}", transient=True) from exc

        if response.status_code >= 400:
            raise PortError(
                f"openrouter returned HTTP {response.status_code}: {response.text[:400]}",
                transient=response.status_code in TRANSIENT_STATUSES,
                status=response.status_code,
            )
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PortError("openrouter returned a non-JSON body", transient=True) from exc
        return body


def _content(body: dict[str, Any]) -> str | None:
    choices = body.get("choices") or []
    if not choices:
        return None
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else None


def _usage(body: dict[str, Any]) -> LLMUsage:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return LLMUsage(prompt_tokens=0, completion_tokens=0)
    return LLMUsage(
        prompt_tokens=_to_int(usage.get("prompt_tokens")),
        completion_tokens=_to_int(usage.get("completion_tokens")),
    )


def _to_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _build(settings: Settings) -> LLMPort:
    creds = settings.llm.openrouter
    if not creds.api_key:
        raise ConfigError("missing LLM__OPENROUTER__API_KEY")
    return OpenRouterLLM(
        api_key=creds.api_key,
        model=settings.llm_model,
        base_url=creds.base_url or DEFAULT_BASE_URL,
        timeout_seconds=settings.llm_timeout_seconds,
    )


register(
    ProviderSpec(
        kind="llm", name="openrouter", build=_build, rate_per_minute=60, label="OpenRouter"
    )
)
