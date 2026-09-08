from __future__ import annotations

import httpx
import pytest
import respx

from interviewer_adapters.llm.openrouter import DEFAULT_BASE_URL, OpenRouterLLM, _build
from interviewer_core.config import LLMCreds, ProviderCreds, Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.llm import LLMMessage

_URL = f"{DEFAULT_BASE_URL}/chat/completions"
_MESSAGES = [LLMMessage(role="user", content="hi")]


def _settings(**overrides: object) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
        **overrides,  # type: ignore[arg-type]
    )


@respx.mock
async def test_complete_success_parses_content_and_usage() -> None:
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello there"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    llm = OpenRouterLLM(api_key="k", model="m")

    answer = await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert answer.text == "hello there"
    assert answer.usage.prompt_tokens == 10
    assert answer.usage.completion_tokens == 5


@respx.mock
async def test_complete_401_is_not_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is False
    assert exc_info.value.status == 401


@respx.mock
async def test_complete_429_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(429, text="slow down"))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True
    assert exc_info.value.status == 429


@respx.mock
async def test_complete_500_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(500, text="boom"))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_malformed_body_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, content=b"not json"))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_200_with_error_field_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"error": {"message": "refused"}}))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert "refused" in str(exc_info.value)


@respx.mock
async def test_complete_timeout_is_transient() -> None:
    respx.post(_URL).mock(side_effect=httpx.TimeoutException("too slow"))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_unreachable_is_transient() -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectError("no route"))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_no_choices_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
    llm = OpenRouterLLM(api_key="k", model="m")

    with pytest.raises(PortError, match="no content"):
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)


@respx.mock
async def test_complete_usage_falls_back_to_zero_on_garbage() -> None:
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": "not-a-number"},
            },
        )
    )
    llm = OpenRouterLLM(api_key="k", model="m")

    answer = await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert answer.usage.prompt_tokens == 0
    assert answer.usage.completion_tokens == 0


def test_build_missing_api_key_raises_config_error_naming_the_var() -> None:
    settings = _settings()

    with pytest.raises(ConfigError, match="LLM__OPENROUTER__API_KEY"):
        _build(settings)


def test_build_with_api_key_returns_configured_port() -> None:
    settings = _settings(llm=LLMCreds(openrouter=ProviderCreds(api_key="abc")))

    llm = _build(settings)

    assert isinstance(llm, OpenRouterLLM)
    assert llm.model == settings.llm_model
