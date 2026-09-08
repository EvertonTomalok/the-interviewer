from __future__ import annotations

import httpx
import pytest
import respx

from interviewer_adapters.llm.openai_compat import OpenAICompatLLM, _build
from interviewer_core.config import LLMCreds, ProviderCreds, Settings
from interviewer_core.errors import ConfigError, PortError
from interviewer_core.ports.llm import LLMMessage

_BASE_URL = "https://model.example.com/v1"
_URL = f"{_BASE_URL}/chat/completions"
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
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )
    )
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    answer = await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert answer.text == "hello there"
    assert answer.usage.prompt_tokens == 7
    assert answer.usage.completion_tokens == 3


@respx.mock
async def test_complete_401_is_not_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is False
    assert exc_info.value.status == 401


@respx.mock
async def test_complete_429_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(429, text="slow down"))
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_malformed_body_is_transient() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, content=b"not json"))
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_200_with_error_field_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"error": {"message": "refused"}}))
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert "refused" in str(exc_info.value)


@respx.mock
async def test_complete_unreachable_is_transient() -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectError("no route"))
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    with pytest.raises(PortError) as exc_info:
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)

    assert exc_info.value.transient is True


@respx.mock
async def test_complete_no_choices_raises() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
    llm = OpenAICompatLLM(api_key="k", model="m", base_url=_BASE_URL)

    with pytest.raises(PortError, match="no content"):
        await llm.complete(_MESSAGES, temperature=0.2, max_tokens=100)


def test_build_missing_api_key_raises_config_error_naming_the_var() -> None:
    settings = _settings(llm=LLMCreds(openai_compat=ProviderCreds(base_url=_BASE_URL)))

    with pytest.raises(ConfigError, match="LLM__OPENAI_COMPAT__API_KEY"):
        _build(settings)


def test_build_missing_base_url_raises_config_error_naming_the_var() -> None:
    settings = _settings(llm=LLMCreds(openai_compat=ProviderCreds(api_key="abc")))

    with pytest.raises(ConfigError, match="LLM__OPENAI_COMPAT__BASE_URL"):
        _build(settings)


def test_build_with_creds_returns_configured_port() -> None:
    settings = _settings(
        llm=LLMCreds(openai_compat=ProviderCreds(api_key="abc", base_url=_BASE_URL))
    )

    llm = _build(settings)

    assert isinstance(llm, OpenAICompatLLM)
    assert llm.model == settings.llm_model
