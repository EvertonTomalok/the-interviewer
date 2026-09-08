"""Admin auth (PRD §8): bcrypt password, JWT HS256. Candidates never touch
this router -- they have no account at all, see `session.py`'s claim route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from interviewer_adapters.persistence import DuplicateKeyError
from interviewer_api import deps
from interviewer_api.envelope import envelope
from interviewer_api.errors import ApiError, unauthorized
from interviewer_api.security import encode_token, hash_secret, verify_secret
from interviewer_core.config import Settings
from interviewer_core.domain.entities import User
from interviewer_core.logging import get_logger
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])
_log = get_logger("interviewer_api.auth")


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    settings: Settings = Depends(deps.get_settings),
    users: UserRepository = Depends(deps.get_user_repo),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    # Candidates have no accounts at all -- this route stays admin-shaped and
    # closed; it never creates anything but an admin.
    if not settings.registration_open:
        raise ApiError(403, "registration_closed", "registration is closed")

    user = User(
        id=ids.new_id(),
        email=body.email,
        password_hash=hash_secret(body.password),
        role="admin",
        created_at=clock.now(),
    )
    try:
        await users.add(user)
    except DuplicateKeyError as exc:
        raise ApiError(409, "email_taken", str(exc)) from exc

    _log.info("admin_registered", user_id=user.id, email=user.email)
    return envelope(data={"id": user.id, "email": user.email})


@router.post("/login")
async def login(
    body: LoginRequest,
    settings: Settings = Depends(deps.get_settings),
    users: UserRepository = Depends(deps.get_user_repo),
    clock: Clock = Depends(deps.get_clock),
) -> dict[str, object]:
    user = await users.get_by_email(body.email)
    if user is None or not verify_secret(body.password, user.password_hash):
        raise unauthorized("invalid email or password")

    now = clock.now()
    access_token = encode_token(
        subject=user.id,
        role="admin",
        secret=settings.auth_secret_key,
        ttl_minutes=settings.access_token_ttl_minutes,
        now=now,
    )
    _log.info("admin_login", user_id=user.id, email=user.email)
    return envelope(data={"access_token": access_token, "token_type": "bearer"})
