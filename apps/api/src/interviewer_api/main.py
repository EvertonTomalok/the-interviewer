"""FastAPI entrypoint.

Routers, auth and the composition root (`deps.py`) land in T09. Until then
this module only proves the image, the compose wiring and the envelope shape
are right -- `/healthz` and `/readyz` are real, everything else is not here
yet.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Adaptive Voice Interviewer API")


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {"success": True, "data": {"status": "ok"}, "error": None, "metadata": None}


@app.get("/readyz")
async def readyz() -> dict[str, object]:
    return {"success": True, "data": {"status": "ok"}, "error": None, "metadata": None}
