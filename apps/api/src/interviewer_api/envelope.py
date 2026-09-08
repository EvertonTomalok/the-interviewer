"""The one response shape: `{success, data, error, metadata}` -- for a
success, a validation error and a domain error alike. Registered on the app
in `main.py`; a route never builds this by hand.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from interviewer_api.errors import ApiError
from interviewer_core.errors import ConfigError, DomainError, PortError


def envelope(
    *,
    data: Any = None,
    error: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"success": error is None, "data": data, "error": error, "metadata": metadata}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(error={"code": exc.code, "message": exc.message}),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=envelope(
                error={"code": "validation_error", "message": "request failed validation"},
                metadata={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=409, content=envelope(error={"code": "domain_error", "message": str(exc)})
        )

    @app.exception_handler(PortError)
    async def _port_error(_: Request, exc: PortError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content=envelope(error={"code": "upstream_error", "message": str(exc)}),
        )

    @app.exception_handler(ConfigError)
    async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=envelope(error={"code": "config_error", "message": str(exc)}),
        )
