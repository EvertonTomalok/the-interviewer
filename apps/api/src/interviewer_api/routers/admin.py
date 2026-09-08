"""Admin-only configuration and review routes (PRD §7): areas, persona
versions, invites, and the one place a score is ever served.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from interviewer_adapters.persistence import DuplicateKeyError
from interviewer_api import deps
from interviewer_api.envelope import envelope
from interviewer_api.errors import ApiError, not_found
from interviewer_api.passkeys import generate_passkey
from interviewer_api.security import TokenClaims, hash_secret
from interviewer_core.config import Settings
from interviewer_core.domain.entities import Area, InterviewInvite, Persona, PersonaQuestion
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import (
    AreaRepository,
    InviteRepository,
    PersonaRepository,
    ReportRepository,
    SessionRepository,
    TurnRepository,
)

router = APIRouter(dependencies=[Depends(deps.require_admin)])


class AreaRequest(BaseModel):
    slug: str
    name: str
    description: str = ""


@router.post("/areas", status_code=201)
async def create_area(
    body: AreaRequest,
    areas: AreaRepository = Depends(deps.get_area_repo),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    area = Area(id=ids.new_id(), slug=body.slug, name=body.name, description=body.description)
    try:
        await areas.add(area)
    except DuplicateKeyError as exc:
        raise ApiError(409, "slug_taken", str(exc)) from exc
    return envelope(
        data={"id": area.id, "slug": area.slug, "name": area.name, "description": area.description}
    )


class QuestionRequest(BaseModel):
    ref: str
    topic: str
    text: str
    expected_answer: str
    weight: float = 1.0
    follow_up_depth: int = 0


class PersonaRequest(BaseModel):
    name: str
    version: int
    language: str = "en"
    voice: str | None = None
    llm_provider: str
    llm_model: str
    temperature: float = 0.4
    max_tokens: int = 800
    timeout_seconds: int = 60
    greeting_text: str
    intake_prompt_text: str
    farewell_text: str
    questions: list[QuestionRequest]
    policy: str = "guided"
    min_coverage: float = 0.7
    max_questions: int = 8
    rubric: str


@router.post("/areas/{area_id}/personas", status_code=201)
async def publish_persona(
    area_id: str,
    body: PersonaRequest,
    areas: AreaRepository = Depends(deps.get_area_repo),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    if await areas.get(area_id) is None:
        raise not_found(f"no area {area_id!r}")

    persona = Persona(
        id=ids.new_id(),
        area_id=area_id,
        name=body.name,
        version=body.version,
        status="published",
        language=body.language,
        voice=body.voice,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        timeout_seconds=body.timeout_seconds,
        greeting_text=body.greeting_text,
        intake_prompt_text=body.intake_prompt_text,
        farewell_text=body.farewell_text,
        questions=tuple(PersonaQuestion(**q.model_dump()) for q in body.questions),
        policy=body.policy,  # type: ignore[arg-type]
        min_coverage=body.min_coverage,
        max_questions=body.max_questions,
        rubric=body.rubric,
        created_at=clock.now(),
    )
    try:
        await personas.add(persona)
    except DuplicateKeyError as exc:
        raise ApiError(409, "version_taken", str(exc)) from exc
    return envelope(data={"id": persona.id, "area_id": persona.area_id, "version": persona.version})


class InviteRequest(BaseModel):
    persona_id: str
    max_sessions: int = 1
    ttl_hours: int | None = None


@router.post("/invites", status_code=201)
async def create_invite(
    body: InviteRequest,
    personas: PersonaRepository = Depends(deps.get_persona_repo),
    invites: InviteRepository = Depends(deps.get_invite_repo),
    settings: Settings = Depends(deps.get_settings),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    if await personas.get(body.persona_id) is None:
        raise not_found(f"no persona {body.persona_id!r}")

    now = clock.now()
    passkey = generate_passkey()
    slug = ids.new_id()
    ttl_hours = body.ttl_hours or settings.invite_ttl_hours
    invite = InterviewInvite(
        id=ids.new_id(),
        slug=slug,
        persona_id=body.persona_id,
        passkey_hash=hash_secret(passkey),
        expires_at=now + timedelta(hours=ttl_hours),
        max_sessions=body.max_sessions,
        used_count=0,
        status="active",
        created_at=now,
    )
    await invites.add(invite)
    url = f"{settings.public_base_url.rstrip('/')}/i/{slug}"
    # Returned once, here, and never again -- not on a later read, not in a
    # log line (see `test_the_passkey_never_comes_back`).
    return envelope(data={"id": invite.id, "slug": slug, "url": url, "passkey": passkey})


@router.delete("/invites/{invite_id}", status_code=204)
async def retire_invite(
    invite_id: str, invites: InviteRepository = Depends(deps.get_invite_repo)
) -> None:
    # `InviteRepository` (T05, frozen) models "retire" as removal: the slug
    # stops resolving, `claim()` on it returns the same typed error as an
    # expired one, and sessions already claimed under it are untouched --
    # nothing references the invite row itself. See apps/api/CONTEXT.md.
    await invites.delete(invite_id)


@router.get("/admin/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    _admin: TokenClaims = Depends(deps.require_admin),
    sessions: SessionRepository = Depends(deps.get_session_repo),
    turns: TurnRepository = Depends(deps.get_turn_repo),
    reports: ReportRepository = Depends(deps.get_report_repo),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
) -> dict[str, object]:
    session = await sessions.get(session_id)
    if session is None:
        raise not_found(f"no session {session_id!r}")

    persona = await personas.get(session.persona_id)
    session_turns = await turns.list_for_session(session_id)
    report = await reports.get_for_session(session_id)

    return envelope(
        data={
            "id": session.id,
            "phase": session.phase,
            "candidate_name": session.candidate_name,
            "persona_id": session.persona_id,
            "persona_version": persona.version if persona else None,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "turns": [
                {
                    "index": t.index,
                    "kind": t.kind,
                    "question_ref": t.question_ref,
                    "transcript": t.transcript,
                    "audio_artifact_id": t.audio_artifact_id,
                    "created_at": t.created_at,
                }
                for t in sorted(session_turns, key=lambda t: t.index)
            ],
            "report": (
                None
                if report is None
                else {
                    "overall_score": report.overall_score,
                    "summary": report.summary,
                    "scores": [
                        {
                            "question_ref": s.question_ref,
                            "score": s.score,
                            "verdict": s.verdict,
                            "rationale": s.rationale,
                        }
                        for s in report.scores
                    ],
                }
            ),
        }
    )
