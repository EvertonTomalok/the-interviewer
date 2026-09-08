"""`{success, data, error, metadata}` -- for a success, a validation error
and a domain error alike (T09's own "Done when").
"""

from __future__ import annotations

from typing import Any

import httpx


async def test_a_success_response_has_every_envelope_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    body = response.json()
    assert set(body) == {"success", "data", "error", "metadata"}
    assert body["success"] is True
    assert body["error"] is None


async def test_a_validation_error_has_every_envelope_key(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/register", json={"email": "a@example.com"}
    )  # missing password
    body = response.json()
    assert response.status_code == 422
    assert set(body) == {"success", "data", "error", "metadata"}
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"
    assert body["data"] is None


async def test_a_domain_error_has_every_envelope_key(
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
        "/session/turns", headers=headers, files={"file": ("a.txt", b"nope", "text/plain")}
    )
    body = response.json()
    assert response.status_code == 409
    assert set(body) == {"success", "data", "error", "metadata"}
    assert body["success"] is False
    assert body["error"]["code"] == "domain_error"
