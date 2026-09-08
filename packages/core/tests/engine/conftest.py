from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from interviewer_core.domain.entities import Persona, PersonaQuestion, Session
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMUsage

_USAGE = LLMUsage(prompt_tokens=1, completion_tokens=1)


class FakeLLM:
    """Scripted `LLMPort` test double -- deterministic, no network."""

    def __init__(self, answers: Sequence[str]) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[LLMMessage, ...]] = []

    async def complete(
        self, messages: Sequence[LLMMessage], *, temperature: float, max_tokens: int
    ) -> LLMAnswer:
        self.calls.append(tuple(messages))
        if not self._answers:
            raise AssertionError("FakeLLM has no scripted answers left")
        return LLMAnswer(text=self._answers.pop(0), usage=_USAGE)


@pytest.fixture
def fake_llm() -> Callable[[Sequence[str]], FakeLLM]:
    return FakeLLM


@pytest.fixture
def question_factory() -> Callable[..., PersonaQuestion]:
    def _make(**overrides: object) -> PersonaQuestion:
        base: dict[str, object] = {
            "ref": "q1",
            "topic": "backend basics",
            "text": "Tell me about a time you optimized a slow query.",
            "expected_answer": "mentions adding an index or rewriting the query plan",
            "weight": 1.0,
            "follow_up_depth": 1,
        }
        base.update(overrides)
        return PersonaQuestion(**base)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def persona_factory(question_factory: Callable[..., PersonaQuestion]) -> Callable[..., Persona]:
    def _make(**overrides: object) -> Persona:
        base: dict[str, object] = {
            "id": "persona-1",
            "area_id": "area-1",
            "name": "Backend v1",
            "version": 1,
            "status": "published",
            "language": "en",
            "voice": None,
            "llm_provider": "fake",
            "llm_model": "fake-model",
            "temperature": 0.4,
            "max_tokens": 800,
            "timeout_seconds": 60,
            "greeting_text": "Welcome!",
            "intake_prompt_text": "Sorry, I didn't catch your name -- could you say it again?",
            "farewell_text": "Thanks for your time, that's everything from me.",
            "questions": (question_factory(),),
            "policy": "guided",
            "min_coverage": 0.7,
            "max_questions": 8,
            "rubric": "Score 0-1: does the answer name a concrete fix, not just a symptom.",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        base.update(overrides)
        return Persona(**base)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def session_factory() -> Callable[..., Session]:
    def _make(**overrides: object) -> Session:
        base: dict[str, object] = {
            "id": "session-1",
            "invite_id": "invite-1",
            "persona_id": "persona-1",
            "phase": "intake",
            "candidate_name": None,
            "name_confidence": None,
            "coverage": {},
            "started_at": datetime(2026, 1, 1, tzinfo=UTC),
            "ended_at": None,
        }
        base.update(overrides)
        return Session(**base)  # type: ignore[arg-type]

    return _make
