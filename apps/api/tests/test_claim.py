from __future__ import annotations

from typing import Any

import httpx


async def test_claim_with_the_right_passkey_returns_a_token_and_the_greeting(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    response = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["access_token"]
    assert body["data"]["greeting_text"] == "Welcome to the interview!"
    assert body["data"]["intake_prompt_text"] == "Sorry, could you say your name again?"
    assert body["data"]["question_total"] == 1


async def test_a_wrong_passkey_and_an_unknown_slug_return_the_same_error_and_status(
    client: httpx.AsyncClient, register_and_login: Any, publish_area_and_persona: Any
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    wrong = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": "not-the-passkey"})
    unknown = await client.post("/i/does-not-exist/claim", json={"passkey": "whatever"})

    assert wrong.status_code == unknown.status_code == 401
    assert (
        wrong.json()["error"]
        == unknown.json()["error"]
        == {
            "code": "invalid_claim",
            "message": "this invite link is not available",
        }
    )


async def test_an_expired_invite_returns_the_same_typed_error(
    client: httpx.AsyncClient, graph: Any, register_and_login: Any, publish_area_and_persona: Any
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    graph.clock.advance(hours=graph.settings.invite_ttl_hours + 1)

    response = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_claim"


async def test_a_retired_invite_returns_the_same_typed_error(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)
    await client.delete(f"/invites/{setup['invite_id']}", headers=auth_header(admin_token))

    response = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_claim"


async def test_an_exhausted_invite_returns_the_same_typed_error(
    client: httpx.AsyncClient,
    auth_header: Any,
    register_and_login: Any,
    publish_area_and_persona: Any,
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    first = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    assert first.status_code == 200

    second = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "invalid_claim"


async def test_the_passkey_appears_once_in_the_invite_response_and_in_no_log_line(
    client: httpx.AsyncClient, register_and_login: Any, publish_area_and_persona: Any
) -> None:
    import logging

    admin_token = await register_and_login(client)

    logger = logging.getLogger("interviewer_api.session")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        setup = await publish_area_and_persona(client, admin_token)
        claim_response = await client.post(
            f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]}
        )
    finally:
        logger.removeHandler(handler)

    # Present once, in the creation response captured by `setup` -- absent
    # from the claim response, which answers with a session token instead.
    assert setup["passkey"] not in claim_response.text
    for record in records:
        rendered = f"{record.getMessage()} {getattr(record, 'context', {})}"
        assert setup["passkey"] not in rendered


async def test_lockout_engages_after_max_attempts_and_a_correct_passkey_still_fails(
    client: httpx.AsyncClient, graph: Any, register_and_login: Any, publish_area_and_persona: Any
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    for _ in range(graph.settings.passkey_max_attempts):
        response = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": "wrong"})
        assert response.status_code == 401

    locked_but_correct = await client.post(
        f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]}
    )
    assert locked_but_correct.status_code == 401
    assert locked_but_correct.json()["error"]["code"] == "invalid_claim"


async def test_lockout_lifts_after_the_window(
    client: httpx.AsyncClient, graph: Any, register_and_login: Any, publish_area_and_persona: Any
) -> None:
    admin_token = await register_and_login(client)
    setup = await publish_area_and_persona(client, admin_token)

    for _ in range(graph.settings.passkey_max_attempts):
        await client.post(f"/i/{setup['slug']}/claim", json={"passkey": "wrong"})

    graph.clock.advance(minutes=graph.settings.passkey_lockout_minutes + 1)

    response = await client.post(f"/i/{setup['slug']}/claim", json={"passkey": setup["passkey"]})
    assert response.status_code == 200
