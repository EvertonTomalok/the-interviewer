"""The full candidate journey, end to end, on `inline` + fakes -- and the
guarantees around it: the route does no work, a double-tap costs one run,
and no score ever reaches a candidate token.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import jwt

from interviewer_adapters.speech.fake_stt import FakeSTT
from interviewer_api.main import app
from interviewer_core.errors import PortError
from interviewer_core.ports.llm import LLMAnswer


def _session_id_from(token: str) -> str:
    payload = jwt.decode(token, options={"verify_signature": False})
    subject: str = payload["sub"]
    return subject


async def test_the_full_interview_end_to_end(
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
    assert claim.status_code == 200
    candidate_token = claim.json()["data"]["access_token"]
    assert claim.json()["data"]["question_total"] == 1
    headers = auth_header(candidate_token)
    session_id = _session_id_from(candidate_token)

    # -- turn 1: intake, name + the only question -------------------------
    graph.script(
        json.dumps({"name": "Ana Ribeiro"}),
        "Tell me about a challenge you solved recently?",
    )
    turn1 = await client.post(
        "/session/turns",
        headers=headers,
        files={"file": ("audio.wav", b"RIFF....WAVEfake", "audio/wav")},
    )
    assert turn1.status_code == 202
    assert turn1.json()["data"]["turn_index"] == 0
    run1 = await poll_run(client, headers, turn1.json()["data"]["run_id"])
    assert run1["status"] == "succeeded"
    assert run1["phase"] == "questioning"
    assert run1["question_text"] == "Tell me about a challenge you solved recently?"
    assert run1["question_number"] == 1
    assert run1["question_total"] == 1
    assert run1["audio_artifact_id"] is None  # text mode

    state = (await client.get("/session", headers=headers)).json()["data"]
    assert state["phase"] == "questioning"
    assert state["candidate_name"] == "Ana Ribeiro"
    assert len(state["turns"]) == 2  # candidate intake + interviewer question

    # -- turn 2: the only answer, which closes the session -----------------
    turn2 = await client.post(
        "/session/turns",
        headers=headers,
        files={"file": ("audio.wav", b"RIFF....WAVEfake2", "audio/wav")},
    )
    assert turn2.status_code == 202
    assert turn2.json()["data"]["turn_index"] == 1
    run2 = await poll_run(client, headers, turn2.json()["data"]["run_id"])
    assert run2["status"] == "succeeded"
    assert run2["phase"] == "closing"
    assert run2["question_text"] == "Thanks, that's everything from me."

    # -- finish: scores the interview, no score reaches this token --------
    graph.script(
        json.dumps(
            {"scores": [{"ref": "q1", "score": 0.8, "verdict": "strong", "rationale": "solid"}]}
        )
    )
    finish = await client.post("/session/finish", headers=headers)
    assert finish.status_code == 202
    eval_run = await poll_run(client, headers, finish.json()["data"]["run_id"])
    assert eval_run == {"status": "succeeded"}  # nothing else -- no score, no verdict

    for response in (
        await client.get("/session", headers=headers),
        await client.get(f"/session/runs/{finish.json()['data']['run_id']}", headers=headers),
    ):
        raw = response.text
        assert '"score"' not in raw
        assert '"verdict"' not in raw
        assert '"rationale"' not in raw

    # -- the admin sees what the candidate never did -----------------------
    detail = await client.get(f"/admin/sessions/{session_id}", headers=auth_header(admin_token))
    detail_data = detail.json()["data"]
    assert detail_data["phase"] == "completed"
    assert detail_data["report"]["overall_score"] == 0.8
    assert detail_data["report"]["scores"][0]["verdict"] == "strong"


async def test_an_answer_after_closing_is_refused_with_409(
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

    graph.script(json.dumps({"name": "Ana"}), "First question, right?")
    t1 = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
    )
    await poll_run(client, headers, t1.json()["data"]["run_id"])
    t2 = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"y", "audio/wav")}
    )
    await poll_run(client, headers, t2.json()["data"]["run_id"])  # now closing

    stray = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"z", "audio/wav")}
    )
    assert stray.status_code == 409
    assert stray.json()["error"]["code"] == "session_closed"


async def test_finish_before_the_intake_turn_is_refused(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    response = await client.post("/session/finish", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_ready_to_finish"


async def test_finish_is_idempotent_one_run_one_report(
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

    graph.script(json.dumps({"name": "Ana"}), "Question one, yes?")
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
            {"scores": [{"ref": "q1", "score": 0.5, "verdict": "adequate", "rationale": "ok"}]}
        )
    )
    first = await client.post("/session/finish", headers=headers)
    await poll_run(client, headers, first.json()["data"]["run_id"])
    second = await client.post("/session/finish", headers=headers)

    assert first.json()["data"]["run_id"] == second.json()["data"]["run_id"]
    session_id = _session_id_from(claim.json()["data"]["access_token"])
    assert graph.reports._by_session[session_id].overall_score == 0.5  # noqa: SLF001


async def test_double_tap_on_the_same_turn_produces_one_run_and_one_turn_pair(
    graph_factory: Any,
    apply_overrides: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
    poll_run: Any,
) -> None:
    class _SlowSTT:
        """Wraps `FakeSTT` with a real, if tiny, delay -- these fakes are
        otherwise instant, which closes the race window a genuine double
        click on send actually opens (the first round's background drive
        finishing before the second request is even parsed). A real
        provider's latency is exactly what makes that window real; this
        stands in for it."""

        def __init__(self) -> None:
            self._inner = FakeSTT()

        async def transcribe(self, audio: Any, *, mime: str, language: str | None = None) -> Any:
            await asyncio.sleep(0.05)
            return await self._inner.transcribe(audio, mime=mime, language=language)

    graph = graph_factory(stt=_SlowSTT())
    apply_overrides(graph)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_token = await register_and_login(client)
            setup = await publish_area_and_persona(client, admin_token)
            claim = await client.post(
                f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]}
            )
            headers = auth_header(claim.json()["data"]["access_token"])

            graph.script(json.dumps({"name": "Ana"}), "Only question, correct?")
            first, second = await asyncio.gather(
                client.post(
                    "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
                ),
                client.post(
                    "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
                ),
            )
            assert first.json()["data"]["run_id"] == second.json()["data"]["run_id"]

            await poll_run(client, headers, first.json()["data"]["run_id"])
            session_id = _session_id_from(claim.json()["data"]["access_token"])
            turns = await graph.turns.list_for_session(session_id)
            assert len(turns) == 2  # one candidate row, one interviewer row -- never four
    finally:
        app.dependency_overrides.clear()


async def test_the_route_does_no_work_and_returns_202_even_when_the_llm_fails(
    graph_factory: Any,
    apply_overrides: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
    poll_run: Any,
) -> None:
    class _BrokenLLM:
        model = "broken"

        async def complete(
            self, messages: Any, *, temperature: float, max_tokens: int
        ) -> LLMAnswer:
            raise PortError("provider is down", transient=False)

    # `graph.llm` has to be broken from construction: the workflow's steps
    # hold a direct reference to it, wired once inside `Graph.__init__` --
    # overriding `deps.get_llm` after the fact would not reach them.
    graph = graph_factory(llm=_BrokenLLM())
    apply_overrides(graph)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_token = await register_and_login(client)
            setup = await publish_area_and_persona(client, admin_token)
            claim = await client.post(
                f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]}
            )
            headers = auth_header(claim.json()["data"]["access_token"])

            response = await client.post(
                "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
            )
            assert response.status_code == 202
            result = await poll_run(client, headers, response.json()["data"]["run_id"])
    finally:
        app.dependency_overrides.clear()

    assert result["status"] == "failed"
    assert "provider is down" in result["error"]


async def test_upload_guards_reject_the_wrong_mime_as_a_typed_4xx(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    response = await client.post(
        "/session/turns",
        headers=headers,
        files={"file": ("a.txt", b"not audio", "text/plain")},
    )
    assert 400 <= response.status_code < 500
    assert response.json()["success"] is False


async def test_upload_guards_reject_an_oversized_file_as_a_typed_4xx(
    client: httpx.AsyncClient,
    graph: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    graph.settings = graph.settings.model_copy(update={"upload_max_bytes": 10})
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    response = await client.post(
        "/session/turns",
        headers=headers,
        files={"file": ("a.wav", b"x" * 1000, "audio/wav")},
    )
    assert 400 <= response.status_code < 500
    assert response.json()["success"] is False


async def test_session_max_turns_caps_the_session_regardless_of_persona(
    client: httpx.AsyncClient,
    graph: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    graph.settings = graph.settings.model_copy(update={"session_max_turns": 0})
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    response = await client.post(
        "/session/turns", headers=headers, files={"file": ("a.wav", b"x", "audio/wav")}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_max_turns"


async def test_an_artifact_from_another_session_is_a_404(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    claim = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers = auth_header(claim.json()["data"]["access_token"])

    response = await client.get("/session/artifacts/does-not-exist", headers=headers)
    assert response.status_code == 404


async def test_a_candidate_token_against_another_sessions_artifact_is_a_404(
    client: httpx.AsyncClient,
    graph: Any,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
    poll_run: Any,
) -> None:
    graph.settings = graph.settings.model_copy(update={"reply_mode": "voice"})
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    claim_a = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    headers_a = auth_header(claim_a.json()["data"]["access_token"])
    session_a = _session_id_from(claim_a.json()["data"]["access_token"])

    invite2 = await client.post(
        "/invites", json={"persona_id": setup["persona_id"]}, headers=auth_header(admin_token)
    )
    invite2_data = invite2.json()["data"]
    claim_b = await client.post(
        f"/i/{invite2_data['slug']}/claim", json={"passkey": invite2_data["passkey"]}
    )
    headers_b = auth_header(claim_b.json()["data"]["access_token"])

    graph.script(json.dumps({"name": "Ana"}), "Only question, right?")
    turn_a = await client.post(
        "/session/turns", headers=headers_a, files={"file": ("a.wav", b"x", "audio/wav")}
    )
    run_a = await poll_run(client, headers_a, turn_a.json()["data"]["run_id"])
    artifact_a = run_a["audio_artifact_id"]

    # The candidate's own audio serves under their own token...
    own = await client.get(f"/session/artifacts/{artifact_a}", headers=headers_a)
    assert own.status_code == 200

    # ...but session B's token never reaches session A's artifact.
    cross = await client.get(f"/session/artifacts/{artifact_a}", headers=headers_b)
    assert cross.status_code == 404
    assert session_a != _session_id_from(claim_b.json()["data"]["access_token"])
