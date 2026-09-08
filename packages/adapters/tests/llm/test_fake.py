from __future__ import annotations

import pytest

from interviewer_adapters.llm.fake import FakeLLM, _build
from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMUsage


def _settings(app_env: str = "dev") -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x/db",
        redis_url="redis://localhost:6379/0",
        app_env=app_env,
    )


async def test_complete_returns_default_when_no_script_set() -> None:
    llm = FakeLLM()

    answer = await llm.complete(
        [LLMMessage(role="user", content="hi")], temperature=0.1, max_tokens=10
    )

    assert answer.text == "Understood."


async def test_complete_pops_scripted_answers_in_order() -> None:
    first = LLMAnswer(text="one", usage=LLMUsage(prompt_tokens=1, completion_tokens=1))
    second = LLMAnswer(text="two", usage=LLMUsage(prompt_tokens=2, completion_tokens=2))
    llm = FakeLLM(answers=[first, second])

    got_first = await llm.complete(
        [LLMMessage(role="user", content="a")], temperature=0.1, max_tokens=10
    )
    got_second = await llm.complete(
        [LLMMessage(role="user", content="b")], temperature=0.1, max_tokens=10
    )

    assert got_first is first
    assert got_second is second


async def test_complete_records_every_call() -> None:
    llm = FakeLLM()
    messages = [LLMMessage(role="system", content="s"), LLMMessage(role="user", content="u")]

    await llm.complete(messages, temperature=0.1, max_tokens=10)

    assert llm.calls == [tuple(messages)]


def test_build_returns_fake_in_dev() -> None:
    llm = _build(_settings(app_env="dev"))

    assert isinstance(llm, FakeLLM)


def test_build_refuses_in_prod() -> None:
    with pytest.raises(ConfigError, match="APP_ENV=prod"):
        _build(_settings(app_env="prod"))
