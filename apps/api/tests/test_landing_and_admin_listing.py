"""`GET /i/{slug}` (the shared link, content-negotiated) and the admin
routes T10's web pages need but T09 didn't ship: the session listing and
an admin-scoped artifact read."""

from __future__ import annotations

import json
from typing import Any

import httpx


async def test_i_slug_returns_the_preview_with_no_credential(
    client: httpx.AsyncClient,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    response = await client.get(f"/i/{setup['slug']}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["persona_name"] == "Backend v1"
    assert data["area_name"] == "Backend"
    assert data["question_total"] == 1


async def test_i_slug_unknown_slug_matches_claims_uniform_error(client: httpx.AsyncClient) -> None:
    response = await client.get("/i/does-not-exist")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_claim"


async def test_i_slug_with_html_accept_serves_the_interview_page(
    client: httpx.AsyncClient,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    response = await client.get(f"/i/{setup['slug']}", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Interview</title>" in response.text


async def test_admin_sessions_lists_newest_first_with_score_after_finish(
    client: httpx.AsyncClient,
    graph: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
    poll_run: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token, max_questions=1)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    graph.script(json.dumps({"name": "Ana"}), "Only question, right?")
    t1 = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
    )
    await poll_run(client, headers, t1.json()["data"]["run_id"])
    t2 = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"y", "audio/wav")}
    )
    await poll_run(client, headers, t2.json()["data"]["run_id"])

    graph.script(
        json.dumps(
            {"scores": [{"ref": "q1", "score": 0.9, "verdict": "strong", "rationale": "ok"}]}
        )
    )
    finish = await client.post("/session/finish", headers=headers)
    await poll_run(client, headers, finish.json()["data"]["run_id"])

    listing = await client.get("/admin/sessions", headers=auth_header(admin_token))
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_name"] == "Ana"
    assert row["area"] == "Backend"
    assert row["persona_version"] == 1
    assert row["phase"] == "completed"
    assert row["overall_score"] == 0.9


async def test_admin_sessions_requires_admin_role(client: httpx.AsyncClient) -> None:
    response = await client.get("/admin/sessions")
    assert response.status_code == 401


async def test_admin_artifact_serves_any_sessions_recording(
    client: httpx.AsyncClient,
    graph: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
    poll_run: Any,
) -> None:
    graph.settings = graph.settings.model_copy(update={"reply_mode": "voice"})
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token, max_questions=1)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    graph.script(json.dumps({"name": "Ana"}), "Only question, right?")
    turn = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
    )
    run = await poll_run(client, headers, turn.json()["data"]["run_id"])
    artifact_id = run["audio_artifact_id"]
    assert artifact_id is not None

    response = await client.get(f"/admin/artifacts/{artifact_id}", headers=auth_header(admin_token))
    assert response.status_code == 200

    missing = await client.get("/admin/artifacts/does-not-exist", headers=auth_header(admin_token))
    assert missing.status_code == 404

    unauthenticated = await client.get(f"/admin/artifacts/{artifact_id}")
    assert unauthenticated.status_code == 401
