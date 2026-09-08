"""Typed API errors. Every route raises `ApiError`; nothing constructs the
envelope's error shape by hand -- see `envelope.py` for how it is rendered.
"""

from __future__ import annotations


class ApiError(Exception):
    """A response the caller should treat as final: a status, a stable
    `code` a client can branch on, and a human `message`."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def unauthorized(message: str = "missing or invalid bearer token") -> ApiError:
    return ApiError(401, "unauthorized", message)


def forbidden(message: str = "not allowed for this token") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


#: What every wrong-passkey, expired, retired or exhausted invite (and an
#: unknown slug) answers with -- one shape, so the route is never an oracle
#: for which of those it was, or whether the slug exists at all.
def invalid_claim() -> ApiError:
    return ApiError(401, "invalid_claim", "this invite link is not available")
