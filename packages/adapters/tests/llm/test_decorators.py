from __future__ import annotations

import pytest

from interviewer_adapters.llm.decorators import InstrumentedLLM, RateLimitedLLM, RetryingLLM
from interviewer_core.errors import PortError
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMUsage

_MESSAGES = [LLMMessage(role="user", content="hi")]
_ANSWER = LLMAnswer(text="ok", usage=LLMUsage(prompt_tokens=1, completion_tokens=1))


class _ScriptedLLM:
    """Raises the scripted errors in order, then answers."""

    model = "scripted"

    def __init__(self, *raises: Exception) -> None:
        self._raises = list(raises)
        self.calls = 0

    async def complete(self, messages: object, *, temperature: float, max_tokens: int) -> LLMAnswer:
        self.calls += 1
        if self._raises:
            raise self._raises.pop(0)
        return _ANSWER


class _AlwaysFailingLLM:
    model = "scripted"

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def complete(self, messages: object, *, temperature: float, max_tokens: int) -> LLMAnswer:
        self.calls += 1
        raise self._error


def _sleep_recorder() -> tuple[list[float], object]:
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


def test_retrying_llm_rejects_a_zero_attempt_budget() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryingLLM(_ScriptedLLM(), max_attempts=0)


def test_rate_limited_llm_rejects_a_zero_rate() -> None:
    with pytest.raises(ValueError, match="rate_per_minute"):
        RateLimitedLLM(_ScriptedLLM(), rate_per_minute=0)


async def test_retrying_llm_retries_transient_then_succeeds() -> None:
    inner = _ScriptedLLM(
        PortError("first", transient=True),
        PortError("second", transient=True),
    )
    delays, sleep = _sleep_recorder()
    retrying = RetryingLLM(inner, max_attempts=3, sleep=sleep, jitter=lambda: 0.0)

    answer = await retrying.complete(_MESSAGES, temperature=0.1, max_tokens=10)

    assert answer is _ANSWER
    assert inner.calls == 3
    assert len(delays) == 2


async def test_retrying_llm_raises_permanent_failure_on_first_attempt() -> None:
    inner = _AlwaysFailingLLM(PortError("nope", transient=False))
    delays, sleep = _sleep_recorder()
    retrying = RetryingLLM(inner, max_attempts=3, sleep=sleep)

    with pytest.raises(PortError):
        await retrying.complete(_MESSAGES, temperature=0.1, max_tokens=10)

    assert inner.calls == 1
    assert delays == []


async def test_retrying_llm_honours_the_attempt_budget() -> None:
    inner = _AlwaysFailingLLM(PortError("still down", transient=True))
    delays, sleep = _sleep_recorder()
    retrying = RetryingLLM(inner, max_attempts=3, sleep=sleep, jitter=lambda: 0.0)

    with pytest.raises(PortError, match="still down"):
        await retrying.complete(_MESSAGES, temperature=0.1, max_tokens=10)

    assert inner.calls == 3
    assert len(delays) == 2


async def test_rate_limited_llm_lets_the_first_call_through_immediately() -> None:
    inner = _ScriptedLLM()
    clock_values = iter([0.0])
    delays, sleep = _sleep_recorder()
    limited = RateLimitedLLM(
        inner, rate_per_minute=1, clock=lambda: next(clock_values), sleep=sleep
    )

    await limited.complete(_MESSAGES, temperature=0.1, max_tokens=10)

    assert inner.calls == 1
    assert delays == []


async def test_rate_limited_llm_makes_the_nplus1th_call_wait() -> None:
    inner = _ScriptedLLM()
    clock_values = iter([0.0, 0.0])
    delays, sleep = _sleep_recorder()
    limited = RateLimitedLLM(
        inner, rate_per_minute=1, clock=lambda: next(clock_values), sleep=sleep
    )

    await limited.complete(_MESSAGES, temperature=0.1, max_tokens=10)
    await limited.complete(_MESSAGES, temperature=0.1, max_tokens=10)

    assert inner.calls == 2
    assert delays == [60.0]


async def test_instrumented_llm_logs_provider_model_latency_and_usage() -> None:
    inner = _ScriptedLLM()
    events: list[tuple[str, dict[str, object]]] = []

    class _StubLogger:
        def info(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    clock_values = iter([0.0, 0.25])
    instrumented = InstrumentedLLM(
        inner, provider="fake", logger=_StubLogger(), clock=lambda: next(clock_values)
    )

    await instrumented.complete(_MESSAGES, temperature=0.1, max_tokens=10)

    assert len(events) == 1
    event, kwargs = events[0]
    assert event == "llm_call"
    assert kwargs["provider"] == "fake"
    assert kwargs["model"] == "scripted"
    assert kwargs["latency_ms"] == 250
    assert kwargs["prompt_tokens"] == 1
    assert kwargs["completion_tokens"] == 1
