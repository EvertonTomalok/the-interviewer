from __future__ import annotations

from typing import Any

import httpx


async def test_duplicate_area_slug_is_a_409(
    client: httpx.AsyncClient, auth_header: Any, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    headers = auth_header(admin_token)
    await client.post("/areas", json={"slug": "backend", "name": "Backend"}, headers=headers)
    second = await client.post(
        "/areas", json={"slug": "backend", "name": "Backend 2"}, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "slug_taken"


async def test_publishing_a_persona_for_an_unknown_area_is_a_404(
    client: httpx.AsyncClient, auth_header: Any, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    body = {
        "name": "X",
        "version": 1,
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "greeting_text": "hi",
        "intake_prompt_text": "name?",
        "farewell_text": "bye",
        "questions": [{"ref": "q1", "topic": "t", "text": "Q?", "expected_answer": "a"}],
        "rubric": "r",
    }
    response = await client.post(
        "/areas/does-not-exist/personas", json=body, headers=auth_header(admin_token)
    )
    assert response.status_code == 404


async def test_duplicate_persona_version_in_the_same_area_is_a_409(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    body = {
        "name": "Backend v1 again",
        "version": 1,
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "greeting_text": "hi",
        "intake_prompt_text": "name?",
        "farewell_text": "bye",
        "questions": [{"ref": "q1", "topic": "t", "text": "Q?", "expected_answer": "a"}],
        "rubric": "r",
    }
    response = await client.post(
        f"/areas/{setup['area_id']}/personas", json=body, headers=auth_header(admin_token)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_taken"


async def test_invite_for_an_unknown_persona_is_a_404(
    client: httpx.AsyncClient, auth_header: Any, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    response = await client.post(
        "/invites", json={"persona_id": "does-not-exist"}, headers=auth_header(admin_token)
    )
    assert response.status_code == 404


async def test_retiring_an_invite_stops_it_claiming_but_keeps_existing_sessions(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    headers = auth_header(admin_token)

    claimed = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    assert claimed.status_code == 200
    candidate_headers = {"Authorization": f"Bearer {claimed.json()['data']['access_token']}"}

    retire = await client.delete(f"/invites/{setup['invite_id']}", headers=headers)
    assert retire.status_code == 204

    # The candidate's own session survives the invite being retired.
    still_alive = await client.get("/session", headers=candidate_headers)
    assert still_alive.status_code == 200


async def test_admin_session_detail_for_an_unknown_id_is_a_404(
    client: httpx.AsyncClient, auth_header: Any, register_and_login: Any
) -> None:
    admin_token = await register_and_login(client)
    response = await client.get("/admin/sessions/does-not-exist", headers=auth_header(admin_token))
    assert response.status_code == 404
