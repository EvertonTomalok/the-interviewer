"""The persona-budget guardrail: `max_questions` counts *distinct*
questions asked (capped at `len(persona.questions)`, see ADR 0004), so a
budget above the question count can never fire and the interview would
loop until `SESSION_MAX_TURNS`. These tests pin the two data-level rules
that keep a published persona terminable by construction.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest


def _persona_body(questions: int) -> dict[str, object]:
    return {
        "name": "Backend v1",
        "version": 1,
        "language": "en",
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "greeting_text": "Welcome to the interview!",
        "intake_prompt_text": "Sorry, could you say your name again?",
        "farewell_text": "Thanks, that's everything from me.",
        "questions": [
            {
                "ref": f"q{i}",
                "topic": "backend",
                "text": f"Question number {i}.",
                "expected_answer": f"expected vocabulary {i}",
            }
            for i in range(1, questions + 1)
        ],
        "policy": "adaptive",
        "min_coverage": 0.5,
        "rubric": "score 0-1 per question",
    }


async def _area_id(client: httpx.AsyncClient, admin_token: str) -> str:
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = await client.post(
        "/areas", json={"slug": "backend", "name": "Backend"}, headers=headers
    )
    area_id: str = response.json()["data"]["id"]
    return area_id


async def test_max_questions_defaults_to_the_question_count(
    client: httpx.AsyncClient, graph: Any, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    area_id = await _area_id(client, admin_token)
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = await client.post(
        f"/areas/{area_id}/personas", json=_persona_body(questions=6), headers=headers
    )

    assert response.status_code == 201
    persona_id = response.json()["data"]["id"]
    persona = await graph.personas.get(persona_id)
    assert persona is not None
    assert persona.max_questions == 6


@pytest.mark.parametrize("budget,questions", [(2, 1), (8, 6), (9, 6)])
async def test_max_questions_above_the_question_count_is_rejected(
    client: httpx.AsyncClient, register_and_login: Any, budget: int, questions: int
) -> None:
    admin_token = await register_and_login(client)
    area_id = await _area_id(client, admin_token)
    headers = {"Authorization": f"Bearer {admin_token}"}
    body = _persona_body(questions=questions) | {"max_questions": budget}

    response = await client.post(f"/areas/{area_id}/personas", json=body, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "max_questions_unreachable"


async def test_max_questions_equal_to_the_question_count_is_accepted(
    client: httpx.AsyncClient, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    area_id = await _area_id(client, admin_token)
    headers = {"Authorization": f"Bearer {admin_token}"}
    body = _persona_body(questions=3) | {"max_questions": 3}

    response = await client.post(f"/areas/{area_id}/personas", json=body, headers=headers)

    assert response.status_code == 201
