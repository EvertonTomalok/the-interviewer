"""FastAPI entrypoint: assembles the app from the routers, the auth
dependency and the composition root -- computes nothing itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from interviewer_adapters.persistence import SessionFactory
from interviewer_api import deps
from interviewer_api.envelope import envelope, register_error_handlers
from interviewer_api.routers import admin, auth, session
from interviewer_core.config import Settings


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # A slug nobody registered fails here, loud, naming it -- not at the
    # first turn with a candidate waiting.
    deps.warm_up()
    yield


app = FastAPI(title="Adaptive Voice Interviewer API", lifespan=_lifespan)
register_error_handlers(app)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(session.router)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return envelope(data={"status": "ok"})


@app.get("/readyz")
async def readyz(
    session_factory: SessionFactory = Depends(deps.get_session_factory),
    settings: Settings = Depends(deps.get_settings),
) -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        async with session_factory() as db_session:
            from sqlalchemy import text

            await db_session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 -- readiness reports the failure, never raises it
        checks["database"] = f"down: {exc}"

    if settings.workflow_provider == "redis":
        try:
            from redis.asyncio import from_url

            client = from_url(settings.redis_url)
            try:
                await client.ping()
            finally:
                await client.aclose()
            checks["workflow"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["workflow"] = f"down: {exc}"
    else:
        checks["workflow"] = "ok"  # inline has no external dependency to ping

    down = {k: v for k, v in checks.items() if v != "ok"}
    if down:
        return JSONResponse(
            status_code=503,
            content=envelope(
                error={"code": "not_ready", "message": "; ".join(down.values())}, metadata=checks
            ),
        )
    return JSONResponse(content=envelope(data={"status": "ok"}, metadata=checks))
