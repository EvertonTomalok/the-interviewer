from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class LLMAnswer:
    text: str
    usage: LLMUsage


class LLMPort(Protocol):
    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMAnswer: ...
