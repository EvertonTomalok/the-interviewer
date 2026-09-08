"""Cross-cutting `LLMPort` wrappers, composed outside the adapter (T02 §core/ports).

Each class implements `LLMPort` by wrapping another `LLMPort`, so they stack
in the composition root -- `InstrumentedLLM(RateLimitedLLM(RetryingLLM(raw)))`
-- and stay individually testable. `RetryingLLM` classifies on
`PortError.transient`, never on a status it had to guess.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence

from interviewer_core.errors import PortError
from interviewer_core.logging import BoundLogger, get_logger
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMPort

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class RetryingLLM:
    """Retries a transient `PortError` with exponential backoff and jitter.

    A permanent failure (`transient=False`) is never retried -- raised on
    the first attempt, budget untouched.
    """

    def __init__(
        self,
        inner: LLMPort,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        sleep: Sleep = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._sleep = sleep
        self._jitter = jitter

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMAnswer:
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self._inner.complete(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
            except PortError as exc:
                if not exc.transient or attempt >= self._max_attempts:
                    raise
                delay = (
                    min(self._base_delay * (2 ** (attempt - 1)), self._max_delay) + self._jitter()
                )
                await self._sleep(delay)


class RateLimitedLLM:
    """Paces calls to at most `rate_per_minute`; the (N+1)th call waits."""

    def __init__(
        self,
        inner: LLMPort,
        *,
        rate_per_minute: int,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if rate_per_minute < 1:
            raise ValueError("rate_per_minute must be at least 1")
        self._inner = inner
        self._interval = 60.0 / rate_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_slot: float | None = None

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMAnswer:
        now = self._clock()
        slot = now if self._next_slot is None else max(now, self._next_slot)
        wait = slot - now
        if wait > 0:
            await self._sleep(wait)
        self._next_slot = slot + self._interval
        return await self._inner.complete(messages, temperature=temperature, max_tokens=max_tokens)


class InstrumentedLLM:
    """Logs provider, model, latency and token usage -- never the key."""

    def __init__(
        self,
        inner: LLMPort,
        *,
        provider: str,
        logger: BoundLogger | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self._inner = inner
        self._provider = provider
        self._log = logger or get_logger("interviewer_adapters.llm")
        self._clock = clock

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMAnswer:
        start = self._clock()
        answer = await self._inner.complete(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        latency_ms = int((self._clock() - start) * 1000)
        self._log.info(
            "llm_call",
            provider=self._provider,
            model=getattr(self._inner, "model", "unknown"),
            latency_ms=latency_ms,
            prompt_tokens=answer.usage.prompt_tokens,
            completion_tokens=answer.usage.completion_tokens,
        )
        return answer
