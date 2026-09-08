from __future__ import annotations

import logging
from typing import Any

import httpx

from interviewer_api.security import encode_token


async def test_registration_closed_returns_403(client: httpx.AsyncClient, graph: Any) -> None:
    graph.settings = graph.settings.model_copy(update={"registration_open": False})
    response = await client.post(
        "/auth/register", json={"email": "a@example.com", "password": "hunter2hunter"}
    )
    body = response.json()
    assert response.status_code == 403
    assert body["success"] is False
    assert body["error"]["code"] == "registration_closed"


async def test_registration_open_returns_201(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/register", json={"email": "a@example.com", "password": "hunter2hunter"}
    )
    assert response.status_code == 201
    assert response.json()["data"]["email"] == "a@example.com"


async def test_login_with_wrong_password_is_unauthorized(client: httpx.AsyncClient) -> None:
    await client.post(
        "/auth/register", json={"email": "a@example.com", "password": "hunter2hunter"}
    )
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_login_with_unknown_email_is_unauthorized(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_a_login_log_line_carries_no_password_and_no_token(
    client: httpx.AsyncClient, register_and_login: Any
) -> None:
    logger = logging.getLogger("interviewer_api.auth")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        token = await register_and_login(client)
    finally:
        logger.removeHandler(handler)

    assert records, "expected at least one log record for register + login"
    for record in records:
        rendered = f"{record.getMessage()} {getattr(record, 'context', {})}"
        assert "hunter2hunter" not in rendered
        assert token not in rendered


async def test_admin_routes_reject_a_missing_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/areas", json={"slug": "x", "name": "X"})
    assert response.status_code == 401


async def test_admin_routes_reject_a_malformed_token(
    client: httpx.AsyncClient, auth_header: Any
) -> None:
    response = await client.post(
        "/areas", json={"slug": "x", "name": "X"}, headers=auth_header("not-a-jwt")
    )
    assert response.status_code == 401


async def test_admin_routes_reject_an_expired_token(
    client: httpx.AsyncClient, graph: Any, auth_header: Any
) -> None:
    expired = encode_token(
        subject="someone",
        role="admin",
        secret=graph.settings.auth_secret_key,
        ttl_minutes=-1,
        now=graph.clock.now(),
    )
    response = await client.post(
        "/areas", json={"slug": "x", "name": "X"}, headers=auth_header(expired)
    )
    assert response.status_code == 401


async def test_a_candidate_token_is_refused_on_every_admin_route(
    client: httpx.AsyncClient, graph: Any, auth_header: Any
) -> None:
    candidate_token = encode_token(
        subject="some-session",
        role="candidate",
        secret=graph.settings.auth_secret_key,
        ttl_minutes=60,
        now=graph.clock.now(),
    )
    headers = auth_header(candidate_token)
    for method, path, body in [
        ("POST", "/areas", {"slug": "x", "name": "X"}),
        ("POST", "/invites", {"persona_id": "p"}),
        ("DELETE", "/invites/inv-1", None),
        ("GET", "/admin/sessions/s1", None),
    ]:
        response = await client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403, f"{method} {path} should refuse a candidate token"
