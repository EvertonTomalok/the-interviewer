"""The candidate-facing surface (PRD §7): claim with a passkey, then the
whole turn loop -- resume, answer, finish -- through a session-scoped
token. No route in this module ever serves a score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from interviewer_adapters.persistence import DuplicateKeyError
from interviewer_adapters.speech.boundary import validate_upload
from interviewer_api import deps
from interviewer_api.envelope import envelope
from interviewer_api.errors import conflict, invalid_claim, not_found
from interviewer_api.passkeys import PasskeyLockout
from interviewer_api.security import encode_token, verify_secret
from interviewer_core.config import Settings
from interviewer_core.domain.entities import Session, WorkflowRun
from interviewer_core.domain.phase import advance
from interviewer_core.engine.coverage import question_numbers
from interviewer_core.logging import get_logger
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import (
    AreaRepository,
    ArtifactRepository,
    InviteRepository,
    PersonaRepository,
    RunRepository,
    SessionRepository,
    TurnRepository,
)
from interviewer_core.ports.storage import BlobStore
from interviewer_core.ports.workflow import WorkflowEngine

router = APIRouter()
_log = get_logger("interviewer_api.session")

#: `apps/web/interview.html`, resolved relative to this file so it works the
#: same from a checkout or from the container image (WORKDIR is the repo
#: root either way -- see `Dockerfile`).
_WEB_DIR = Path(__file__).resolve().parents[5] / "apps" / "web"


async def _start_run(
    *,
    workflow: str,
    payload: dict[str, Any],
    idempotency_key: str,
    run_repo: RunRepository,
    engine: WorkflowEngine,
    clock: Clock,
    ids: IdGenerator,
) -> str:
    """Idempotent, non-blocking start: the row is created (or found) here,
    synchronously, so the route can answer with its id; driving the
    workflow happens in the background either way, and a second call with
    the same key joins the first run instead of spawning a second drive."""
    existing = await run_repo.get_by_idempotency_key(idempotency_key)
    if existing is not None:
        return existing.id

    now = clock.now()
    run = WorkflowRun(
        id=ids.new_id(),
        workflow=workflow,
        idempotency_key=idempotency_key,
        status="running",
        input=payload,
        error=None,
        created_at=now,
        updated_at=now,
    )
    try:
        await run_repo.add(run)
    except DuplicateKeyError:
        existing = await run_repo.get_by_idempotency_key(idempotency_key)
        assert existing is not None
        return existing.id

    deps.spawn(
        f"{workflow}:{run.id}", engine.start(workflow, payload, idempotency_key=idempotency_key)
    )
    return run.id


# --- the shared link: the page for a browser, a preview for the page's own JS --


@router.get("/i/{slug}", response_model=None)
async def invite_landing(
    slug: str,
    request: Request,
    invites: InviteRepository = Depends(deps.get_invite_repo),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
    areas: AreaRepository = Depends(deps.get_area_repo),
    clock: Clock = Depends(deps.get_clock),
) -> dict[str, object] | Response:
    """The one URL a candidate is ever sent. A browser navigating here
    (`Accept: text/html`) gets `interview.html` itself; the page's own
    `fetch()` (no `text/html` preference) gets the no-credential preview --
    area, persona name, question count, nothing a wrong guess could use to
    tell one invite state from another (same uniform shape as `claim`)."""
    if "text/html" in request.headers.get("accept", ""):
        return FileResponse(_WEB_DIR / "interview.html")

    invite = await invites.get_by_slug(slug)
    if invite is None or not invite.is_claimable(clock.now()).claimable:
        raise invalid_claim()
    persona = await personas.get(invite.persona_id)
    if persona is None:
        raise invalid_claim()
    area = await areas.get(persona.area_id)

    return envelope(
        data={
            "area_name": area.name if area else "",
            "persona_name": persona.name,
            "question_total": len(persona.questions),
        }
    )


# --- claim -------------------------------------------------------------------


class ClaimRequest(BaseModel):
    passkey: str


@router.post("/i/{slug}/claim")
async def claim(
    slug: str,
    body: ClaimRequest,
    invites: InviteRepository = Depends(deps.get_invite_repo),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
    sessions: SessionRepository = Depends(deps.get_session_repo),
    settings: Settings = Depends(deps.get_settings),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
    lockout: PasskeyLockout = Depends(deps.get_passkey_lockout),
) -> dict[str, object]:
    now = clock.now()
    # Locked, unknown slug, wrong passkey, expired, retired, exhausted: one
    # error, one status, for all of them -- this endpoint is not an oracle
    # for which links exist or why one stopped working.
    if lockout.is_locked(slug, now=now):
        raise invalid_claim()

    invite = await invites.get_by_slug(slug)
    if invite is None or not verify_secret(body.passkey, invite.passkey_hash):
        lockout.record_failure(slug, now=now)
        raise invalid_claim()

    claimed = await invites.claim(slug, now)
    if claimed is None:
        lockout.record_failure(slug, now=now)
        raise invalid_claim()

    persona = await personas.get(claimed.persona_id)
    if persona is None:
        raise invalid_claim()

    lockout.record_success(slug)
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

    # No run started, no model called: the candidate's first screen is
    # authored text, served straight from the pinned persona.
    access_token = encode_token(
        subject=session.id,
        role="candidate",
        secret=settings.auth_secret_key,
        ttl_minutes=settings.candidate_token_ttl_minutes,
        now=now,
    )
    _log.info("invite_claimed", slug=slug, session_id=session.id)
    return envelope(
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "greeting_text": persona.greeting_text,
            "intake_prompt_text": persona.intake_prompt_text,
            "question_total": len(persona.questions),
        }
    )


# --- session resume, turns, finish -----------------------------------------


@router.get("/session")
async def get_state(
    session: Session = Depends(deps.require_candidate_session),
    personas: PersonaRepository = Depends(deps.get_persona_repo),
    turns: TurnRepository = Depends(deps.get_turn_repo),
) -> dict[str, object]:
    persona = await personas.get(session.persona_id)
    assert persona is not None  # a session always pins a persona that existed at claim time

    session_turns = sorted(await turns.list_for_session(session.id), key=lambda t: t.index)
    interviewer_turns = [t for t in session_turns if t.index % 2 == 1]
    question_text = interviewer_turns[-1].transcript if interviewer_turns else persona.greeting_text
    number, total = question_numbers(persona, session.coverage)

    return envelope(
        data={
            "phase": session.phase,
            "candidate_name": session.candidate_name,
            "question_number": number,
            "question_total": total,
            "question_text": question_text,
            "turns": [
                {
                    "index": t.index,
                    "kind": t.kind,
                    "transcript": t.transcript,
                    "audio_artifact_id": t.audio_artifact_id,
                }
                for t in session_turns
            ],
        }
    )


#: Phases a candidate may still speak in. Anything past this and a reply is
#: a stray turn, not a late one -- see `conflict("session_closed", ...)`.
_OPEN_PHASES = ("intake", "questioning")


@router.post("/session/turns", status_code=202)
async def submit_turn(
    file: UploadFile,
    language: str | None = Form(default=None),
    session: Session = Depends(deps.require_candidate_session),
    settings: Settings = Depends(deps.get_settings),
    storage: BlobStore = Depends(deps.get_storage),
    turns: TurnRepository = Depends(deps.get_turn_repo),
    run_repo: RunRepository = Depends(deps.get_run_repo),
    engine: WorkflowEngine = Depends(deps.get_workflow_engine),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    if session.phase not in _OPEN_PHASES:
        raise conflict("session_closed", f"cannot submit a turn in phase {session.phase!r}")

    existing_turns = await turns.list_for_session(session.id)
    turn_index = len(existing_turns) // 2
    if turn_index >= settings.session_max_turns:
        raise conflict("session_max_turns", "this session has reached its turn limit")

    content = await file.read()
    mime = file.content_type or "application/octet-stream"
    validate_upload(
        content, mime=mime, settings=settings
    )  # raises DomainError -> 409, global handler

    # The request is the only moment these bytes exist outside the store:
    # `persist_audio` (inside the workflow) turns this staged upload into
    # the durable `Artifact` row. Nothing here computes on the audio.
    staging_uri = await storage.put(
        f"sessions/{session.id}/uploads/{turn_index}", content, mime=mime
    )

    payload: dict[str, Any] = {
        "session_id": session.id,
        "persona_id": session.persona_id,
        "turn_index": turn_index,
        "staging_uri": staging_uri,
        "mime": mime,
        "language": language,
        "reply_mode": settings.reply_mode,
        "voice": settings.tts_voice or None,
    }
    run_id = await _start_run(
        workflow="turn",
        payload=payload,
        idempotency_key=f"{session.id}:{turn_index}",
        run_repo=run_repo,
        engine=engine,
        clock=clock,
        ids=ids,
    )
    return envelope(data={"run_id": run_id, "turn_index": turn_index})


@router.post("/session/finish", status_code=202)
async def finish(
    session: Session = Depends(deps.require_candidate_session),
    sessions: SessionRepository = Depends(deps.get_session_repo),
    run_repo: RunRepository = Depends(deps.get_run_repo),
    engine: WorkflowEngine = Depends(deps.get_workflow_engine),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGenerator = Depends(deps.get_ids),
) -> dict[str, object]:
    if session.phase not in ("closing", "evaluating", "completed"):
        raise conflict("not_ready_to_finish", f"cannot finish in phase {session.phase!r}")

    if session.phase == "closing":
        # `commit_report` requires this transition already applied and
        # persisted -- see workflow/CONTEXT.md's Traps.
        evaluating = advance(session, "start_evaluation")
        await sessions.update(evaluating)

    run_id = await _start_run(
        workflow="evaluation",
        payload={"session_id": session.id, "persona_id": session.persona_id},
        idempotency_key=f"{session.id}:report",
        run_repo=run_repo,
        engine=engine,
        clock=clock,
        ids=ids,
    )
    return envelope(data={"run_id": run_id})


@router.get("/session/runs/{run_id}")
async def get_run(
    run_id: str,
    session: Session = Depends(deps.require_candidate_session),
    turns: TurnRepository = Depends(deps.get_turn_repo),
    run_repo: RunRepository = Depends(deps.get_run_repo),
    engine: WorkflowEngine = Depends(deps.get_workflow_engine),
) -> dict[str, object]:
    run = await run_repo.get(run_id)
    if run is None or run.input.get("session_id") != session.id:
        raise not_found(f"no run {run_id!r}")

    state = await engine.status(run_id)

    if run.workflow == "evaluation":
        # An evaluation run answers a candidate token with the outcome and
        # nothing else -- no score, no verdict, no rationale ever reaches
        # this side of the token.
        if state.status == "succeeded":
            return envelope(data={"status": "succeeded"})
        data: dict[str, object] = {"status": state.status}
        if state.status == "failed":
            data["error"] = state.error
        return envelope(data=data)

    if state.status != "succeeded":
        data = {"status": state.status}
        if state.status == "failed":
            data["error"] = state.error
        return envelope(data=data)

    compose = dict(state.outputs.get("compose", {}))
    commit = dict(state.outputs.get("commit_turn", {}))
    audio_artifact_id: str | None = None
    interviewer_turn_id = commit.get("interviewer_turn_id")
    if interviewer_turn_id:
        session_turns = await turns.list_for_session(session.id)
        match = next((t for t in session_turns if t.id == interviewer_turn_id), None)
        audio_artifact_id = match.audio_artifact_id if match else None

    return envelope(
        data={
            "status": "succeeded",
            "transcript": state.outputs.get("transcribe", {}).get("text"),
            "question_text": compose.get("text"),
            "question_number": compose.get("question_number"),
            "question_total": compose.get("question_total"),
            "phase": compose.get("session_phase"),
            "audio_artifact_id": audio_artifact_id,
            "coverage": compose.get("session_coverage"),
            "degraded": compose.get("degraded"),
        }
    )


@router.get("/session/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    session: Session = Depends(deps.require_candidate_session),
    artifacts: ArtifactRepository = Depends(deps.get_artifact_repo),
    storage: BlobStore = Depends(deps.get_storage),
) -> Response:
    artifact = await artifacts.get(artifact_id)
    if artifact is None or artifact.session_id != session.id:
        raise not_found(f"no artifact {artifact_id!r}")
    content = await storage.get(artifact.uri)
    return Response(content=content, media_type=artifact.mime)
