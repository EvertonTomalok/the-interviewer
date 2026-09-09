"""`GET /jobs` and `POST /jobs/{area_id}/start`: public, no credential --
browse the sample roles, click one, and land in the same session-token
world `POST /i/{slug}/claim` does.
"""

from __future__ import annotations

from typing import Any

import httpx


async def _publish(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    slug: str,
    name: str,
    persona_name: str,
) -> str:
    headers = {"Authorization": f"Bearer {admin_token}"}
    area_resp = await client.post(
        "/areas", json={"slug": slug, "name": name, "description": f"{name} role"}, headers=headers
    )
    area_id: str = area_resp.json()["data"]["id"]
    persona_body = {
        "name": persona_name,
        "version": 1,
        "language": "en",
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "greeting_text": "Welcome!",
        "intake_prompt_text": "What's your name?",
        "farewell_text": "Thanks for your time.",
        "questions": [
            {
                "ref": "q1",
                "topic": "general",
                "text": "Tell me about a project you're proud of.",
                "expected_answer": "mentions a concrete project",
            },
            {
                "ref": "q2",
                "topic": "general",
                "text": "Walk me through a bug you fixed.",
                "expected_answer": "mentions root cause",
                "follow_up_depth": 1,
            },
        ],
        "policy": "adaptive",
        "min_coverage": 0.6,
        "rubric": "score 0-1 per question",
    }
    await client.post(f"/areas/{area_id}/personas", json=persona_body, headers=headers)
    return area_id


async def test_list_jobs_is_empty_with_no_published_personas(client: httpx.AsyncClient) -> None:
    response = await client.get("/jobs")
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["jobs"] == []


async def test_list_jobs_returns_one_row_per_area_with_a_published_persona(
    client: httpx.AsyncClient, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    await _publish(
        client, admin_token, slug="backend-py", name="Backend Engineer", persona_name="Python SWE"
    )
    await _publish(
        client, admin_token, slug="frontend", name="Frontend Engineer", persona_name="React SWE"
    )

    response = await client.get("/jobs")
    jobs = response.json()["data"]["jobs"]

    assert {j["slug"] for j in jobs} == {"backend-py", "frontend"}
    backend = next(j for j in jobs if j["slug"] == "backend-py")
    assert backend["title"] == "Python SWE"
    assert backend["description"] == "Backend Engineer role"
    assert backend["question_total"] == 2


async def test_start_job_on_unknown_area_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post("/jobs/nope/start")

    assert response.status_code == 404


async def test_start_job_returns_a_usable_candidate_token(
    client: httpx.AsyncClient, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    area_id = await _publish(
        client, admin_token, slug="backend-py", name="Backend Engineer", persona_name="Python SWE"
    )

    start = await client.post(f"/jobs/{area_id}/start")
    data = start.json()["data"]

    assert start.status_code == 200
    assert data["title"] == "Python SWE"
    assert data["question_total"] == 2

    state = await client.get(
        "/session", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert state.status_code == 200
    assert state.json()["data"]["phase"] == "intake"


async def test_start_job_twice_issues_two_independent_sessions(
    client: httpx.AsyncClient, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    area_id = await _publish(
        client, admin_token, slug="backend-py", name="Backend Engineer", persona_name="Python SWE"
    )

    first = await client.post(f"/jobs/{area_id}/start")
    second = await client.post(f"/jobs/{area_id}/start")

    assert first.json()["data"]["access_token"] != second.json()["data"]["access_token"]
    for token in (first.json()["data"]["access_token"], second.json()["data"]["access_token"]):
        state = await client.get("/session", headers={"Authorization": f"Bearer {token}"})
        assert state.status_code == 200
