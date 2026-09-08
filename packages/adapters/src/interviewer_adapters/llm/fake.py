"""Scripted `LLMPort` double, registered as a real provider (PRD §6).

`LLM_PROVIDER=fake` is what lets a clean clone conduct a whole interview
before anyone has an API key. It costs nothing, is never rate-limited, and
every other lane's unit suite runs on it -- so it is refused under
`APP_ENV=prod`, where a silent fake would be worse than a missing key.
"""

from __future__ import annotations

from collections.abc import Sequence

from interviewer_core.config import Settings
from interviewer_core.errors import ConfigError
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMPort, LLMUsage
from interviewer_core.registry import ProviderSpec, register


class FakeLLM:
    """Answers from a script the caller sets; records every call it saw."""

    model = "fake"

    def __init__(
        self,
        answers: Sequence[LLMAnswer] | None = None,
        *,
        default_text: str = "Understood.",
    ) -> None:
        self._answers: list[LLMAnswer] = list(answers) if answers else []
        self._default_text = default_text
        self.calls: list[tuple[LLMMessage, ...]] = []

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMAnswer:
        self.calls.append(tuple(messages))
        if self._answers:
            return self._answers.pop(0)
        return LLMAnswer(
            text=self._default_text, usage=LLMUsage(prompt_tokens=0, completion_tokens=0)
        )


def _build(settings: Settings) -> LLMPort:
    if settings.app_env == "prod":
        raise ConfigError("LLM_PROVIDER=fake is refused when APP_ENV=prod")
    return FakeLLM()


register(
    ProviderSpec(
        kind="llm", name="fake", build=_build, rate_per_minute=10_000, label="Fake (scripted)"
    )
)
