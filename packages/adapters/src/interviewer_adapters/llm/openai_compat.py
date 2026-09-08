"""Adapter for any OpenAI-shaped `/chat/completions` endpoint.

Same wire format as `openrouter.py`, minus the OpenRouter-only headers and
usage-billing extras. This is the adapter that makes a take-home endpoint or
a local model server interchangeable with a hosted one: same `LLM_MODEL`
shape, `LLM_PROVIDER=openai_compat` is the only env flip.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from interviewer_adapters.llm.openrouter import TRANSIENT_STATUSES
from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMPort, LLMUsage
from interviewer_core.registry import ProviderSpec, register


class OpenAICompatLLM:
    """Satisfies `LLMPort` against any OpenAI-compatible `/chat/completions`."""

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
                f"openai_compat returned an error body: {str(body['error'])[:400]}",
                transient=True,
            )

        content = _content(body)
        if content is None:
            raise PortError("openai_compat returned no content", transient=True)

        return LLMAnswer(text=content, usage=_usage(body))

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise PortError(f"openai_compat timed out: {exc}", transient=True) from exc
        except httpx.HTTPError as exc:
            raise PortError(f"openai_compat unreachable: {exc}", transient=True) from exc

        if response.status_code >= 400:
            raise PortError(
                f"openai_compat returned HTTP {response.status_code}: {response.text[:400]}",
                transient=response.status_code in TRANSIENT_STATUSES,
                status=response.status_code,
            )
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PortError("openai_compat returned a non-JSON body", transient=True) from exc
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
    creds = settings.llm.openai_compat
    if not creds.api_key:
        raise ConfigError("missing LLM__OPENAI_COMPAT__API_KEY")
    if not creds.base_url:
        raise ConfigError("missing LLM__OPENAI_COMPAT__BASE_URL")
    return OpenAICompatLLM(
        api_key=creds.api_key,
        model=settings.llm_model,
        base_url=creds.base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )


register(
    ProviderSpec(
        kind="llm",
        name="openai_compat",
        build=_build,
        rate_per_minute=60,
        label="OpenAI-compatible",
    )
)
