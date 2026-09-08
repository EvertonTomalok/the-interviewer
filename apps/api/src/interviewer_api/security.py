"""Password and passkey hashing (bcrypt), JWT encode/decode (HS256). Pure
functions -- no FastAPI, no repository. The dependencies that turn a bearer
token into a principal live in `deps.py`, next to the repositories they need.

Expiry is checked against the injected `Clock`, not PyJWT's own `exp`
validation (real wall-clock time, unconditionally) -- this app never reads
wall-clock time directly anywhere else, and a token minted with a frozen
test clock set to an arbitrary date must not read as expired the moment
it's decoded. `SystemClock` in production makes the two equivalent; only
tests can tell the difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import bcrypt
import jwt

from interviewer_api.errors import unauthorized

ALGORITHM = "HS256"

Role = Literal["admin", "candidate"]


def hash_secret(value: str) -> str:
    """Used for both account passwords and invite passkeys -- same hash,
    same comparison, same never-log-the-plaintext discipline."""
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_secret(value: str, value_hash: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode("utf-8"), value_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    role: Role


def encode_token(*, subject: str, role: Role, secret: str, ttl_minutes: int, now: datetime) -> str:
    expires_at = now + timedelta(minutes=ttl_minutes)
    payload = {"sub": subject, "role": role, "exp_at": expires_at.isoformat()}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, *, secret: str, now: datetime) -> TokenClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"verify_exp": False})
    except jwt.PyJWTError as exc:
        raise unauthorized("token is missing, malformed or expired") from exc

    subject = payload.get("sub")
    role = payload.get("role")
    expires_raw = payload.get("exp_at")
    if not isinstance(subject, str) or role not in ("admin", "candidate"):
        raise unauthorized("token is missing, malformed or expired")
    if not isinstance(expires_raw, str):
        raise unauthorized("token is missing, malformed or expired")
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError as exc:
        raise unauthorized("token is missing, malformed or expired") from exc
    if now >= expires_at:
        raise unauthorized("token is missing, malformed or expired")

    return TokenClaims(subject=subject, role=role)
