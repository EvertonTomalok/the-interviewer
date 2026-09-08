"""Public, no-credential job browsing and one-click interview start.

Distinct from the admin-issued `/i/{slug}` link (PRD §7): here the
candidate never sees a passkey. Starting a job mints a single-use
`InterviewInvite` server-side, claims it immediately, and hands back the
same session-scoped token `POST /i/{slug}/claim` would -- every route past
this one (`/session/*`) is unchanged.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends

from interviewer_api import deps
from interviewer_api.envelope import envelope
from interviewer_api.errors import not_found
from interviewer_api.passkeys import generate_passkey
from interviewer_api.security import encode_token, hash_secret
from interviewer_core.config import Settings
from interviewer_core.domain.entities import InterviewInvite, Session
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import (
    AreaRepository,
    InviteRepository,
    PersonaRepository,
    SessionRepository,
)

router = APIRouter()

#: An ephemeral, self-claimed invite only needs to survive the click -- long
#: enough that a slow page load never races it, never so long it lingers.
_EPHEMERAL_INVITE_TTL_HOURS = 1


@router.get("/jobs")
async def list_jobs(
    areas: AreaRepository = Depends(deps.get_area_repo),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
) -> dict[str, object]:
    jobs: list[dict[str, object]] = []
    for area in await areas.list():
        persona = await personas.latest_published(area.id)
        if persona is None:
            continue
        jobs.append(
            {
                "area_id": area.id,
                "slug": area.slug,
                "title": persona.name,
                "description": area.description,
                "question_total": len(persona.questions),
            }
        )
    return envelope(data={"jobs": jobs})


@router.post("/jobs/{area_id}/start")
async def start_job(
    area_id: str,
    areas: AreaRepository = Depends(deps.get_area_repo),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
    invites: InviteRepository = Depends(deps.get_invite_repo),
    sessions: SessionRepository = Depends(deps.get_session_repo),
    settings: Settings = Depends(deps.get_settings),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    area = await areas.get(area_id)
    if area is None:
        raise not_found(f"no job {area_id!r}")
    persona = await personas.latest_published(area_id)
    if persona is None:
        raise not_found(f"no job {area_id!r}")

    now = clock.now()
    invite = InterviewInvite(
        id=ids.new_id(),
        slug=ids.new_id(),
        persona_id=persona.id,
        passkey_hash=hash_secret(generate_passkey()),
        expires_at=now + timedelta(hours=_EPHEMERAL_INVITE_TTL_HOURS),
        max_sessions=1,
        used_count=0,
        status="active",
        created_at=now,
    )
    await invites.add(invite)
    claimed = await invites.claim(invite.slug, now)
    assert claimed is not None  # just created above, nothing else can have raced it

    session = Session(
        id=ids.new_id(),
        invite_id=claimed.id,
        persona_id=persona.id,
        phase="intake",
        candidate_name=None,
        name_confidence=None,
        coverage={},
        started_at=now,
        ended_at=None,
    )
    await sessions.add(session)

    access_token = encode_token(
        subject=session.id,
        role="candidate",
        secret=settings.auth_secret_key,
        ttl_minutes=settings.candidate_token_ttl_minutes,
        now=now,
    )
    return envelope(
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "title": persona.name,
            "greeting_text": persona.greeting_text,
            "intake_prompt_text": persona.intake_prompt_text,
            "question_total": len(persona.questions),
        }
    )
