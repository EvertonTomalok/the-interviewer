from __future__ import annotations

import httpx

from interviewer_api import deps
from interviewer_api.main import app


async def test_healthz_reports_ok_with_no_dependency_touched() -> None:
    """No settings, no database, no fake registered anywhere -- `/healthz`
    must answer before any of that exists."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


async def test_readyz_reports_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["status"] == "ok"
    assert body["metadata"] == {"database": "ok", "workflow": "ok"}


async def test_readyz_reports_which_dependency_is_down(client: httpx.AsyncClient) -> None:
    def _broken_session_factory() -> object:
        raise ConnectionError("no route to host")

    app.dependency_overrides[deps.get_session_factory] = lambda: _broken_session_factory
    try:
        response = await client.get("/readyz")
    finally:
        del app.dependency_overrides[deps.get_session_factory]

    body = response.json()
    assert response.status_code == 503  # never a 500 -- the route never raises
    assert body["success"] is False
    assert body["error"]["code"] == "not_ready"
    assert "no route to host" in body["metadata"]["database"]
    assert body["metadata"]["workflow"] == "ok"
