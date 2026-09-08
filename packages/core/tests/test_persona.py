from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from interviewer_core.domain import Persona, PersonaQuestion
from interviewer_core.errors import DomainError


def _question(**overrides: object) -> PersonaQuestion:
    base = {
        "ref": "q1",
        "topic": "basics",
        "text": "Tell me about X",
        "expected_answer": "mentions Y",
    }
    base.update(overrides)
    return PersonaQuestion(**base)  # type: ignore[arg-type]


def _persona(**overrides: object) -> Persona:
    base = {
        "id": "p1",
        "area_id": "a1",
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
        "greeting_text": "Hello",
        "intake_prompt_text": "What's your name?",
        "farewell_text": "Thanks, goodbye",
        "questions": (_question(),),
        "policy": "guided",
        "min_coverage": 1.0,
        "max_questions": 8,
        "rubric": "score 0-1 per question",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return Persona(**base)  # type: ignore[arg-type]


def test_question_missing_expected_answer_fails_at_construction() -> None:
    with pytest.raises(DomainError, match="expected_answer"):
        _question(expected_answer="")


def test_question_missing_ref_fails_at_construction() -> None:
    with pytest.raises(DomainError):
        _question(ref="")


def test_duplicate_refs_in_one_persona_are_refused() -> None:
    with pytest.raises(DomainError, match="duplicate"):
        _persona(questions=(_question(ref="q1"), _question(ref="q1", text="other")))


def test_a_published_version_is_immutable() -> None:
    persona = _persona()
    updated = replace(persona, status="retired")
    assert persona.status == "published"
    assert updated.status == "retired"
    assert persona is not updated
