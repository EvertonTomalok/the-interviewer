"""The composition root (PRD's own words for it): every port's real adapter,
built once from settings, and reused for the life of the process.

Every dependency below is `@lru_cache`d -- called once, the return value
kept forever, the FastAPI-standard way to get a process-lifetime singleton
out of `Depends()`. A test overrides one with
`app.dependency_overrides[get_x] = lambda: fake_x`; nothing here is ever
imported and called directly by a router or a test.

**`deps.py` is append-only during parallel waves.** A new provider kind, a
new repository, a new dependency: add a function at the end of the matching
section. Reordering or restructuring what is already here is how two
branches editing the same file collide.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import interviewer_adapters  # noqa: F401 -- import side effect: registers every provider
from interviewer_adapters.llm.decorators import InstrumentedLLM, RateLimitedLLM, RetryingLLM
from interviewer_adapters.persistence import (
    SessionFactory,
    SqlAreaRepository,
    SqlArtifactRepository,
    SqlInviteRepository,
    SqlPersonaRepository,
    SqlReportRepository,
    SqlRunRepository,
    SqlSessionRepository,
    SqlTurnRepository,
    SqlUserRepository,
    make_engine,
    make_session_factory,
)
from interviewer_adapters.workflow.base import StepRecordStore
from interviewer_adapters.workflow.evaluation_steps import build_evaluation_steps
from interviewer_adapters.workflow.sql_step_records import SqlStepRecordStore
from interviewer_adapters.workflow.turn_steps import build_turn_steps
from interviewer_api.errors import forbidden, unauthorized
from interviewer_api.passkeys import PasskeyLockout
from interviewer_api.security import TokenClaims, decode_token
from interviewer_core.config import Settings, load_settings
from interviewer_core.domain.entities import Session
from interviewer_core.engine import TurnPipeline
from interviewer_core.logging import get_logger
from interviewer_core.ports.clock import Clock, SystemClock
from interviewer_core.ports.ids import IdGenerator, Uuid7Ids
from interviewer_core.ports.llm import LLMPort
from interviewer_core.ports.repositories import (
    AreaRepository,
    ArtifactRepository,
    InviteRepository,
    PersonaRepository,
    ReportRepository,
    RunRepository,
    SessionRepository,
    TurnRepository,
    UserRepository,
)
from interviewer_core.ports.speech import SpeechToTextPort, TextToSpeechPort
from interviewer_core.ports.storage import BlobStore
from interviewer_core.ports.workflow import WorkflowEngine
from interviewer_core.registry import require_spec

# --- settings and process-wide primitives -----------------------------------


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@lru_cache
def get_clock() -> Clock:
    return SystemClock()


@lru_cache
def get_ids() -> IdGenerator:
    return Uuid7Ids()


# --- database ----------------------------------------------------------------


@lru_cache
def get_session_factory() -> SessionFactory:
    engine = make_engine(get_settings().database_url)
    return make_session_factory(engine)


# --- repositories --------------------------------------------------------


@lru_cache
def get_user_repo() -> UserRepository:
    return SqlUserRepository(get_session_factory())


@lru_cache
def get_area_repo() -> AreaRepository:
    return SqlAreaRepository(get_session_factory())


@lru_cache
def get_persona_repo() -> PersonaRepository:
    return SqlPersonaRepository(get_session_factory())


@lru_cache
def get_invite_repo() -> InviteRepository:
    return SqlInviteRepository(get_session_factory())


@lru_cache
def get_session_repo() -> SessionRepository:
    return SqlSessionRepository(get_session_factory())


@lru_cache
def get_turn_repo() -> TurnRepository:
    return SqlTurnRepository(get_session_factory())


@lru_cache
def get_artifact_repo() -> ArtifactRepository:
    return SqlArtifactRepository(get_session_factory())


@lru_cache
def get_report_repo() -> ReportRepository:
    return SqlReportRepository(get_session_factory())


@lru_cache
def get_run_repo() -> RunRepository:
    return SqlRunRepository(get_session_factory())


# --- provider ports: resolved through the registry, decorated once ---------


@lru_cache
def get_llm() -> LLMPort:
    settings = get_settings()
    spec = require_spec("llm", settings.llm_provider)
    raw = spec.build(settings)
    retrying = RetryingLLM(raw)
    limited = RateLimitedLLM(retrying, rate_per_minute=spec.rate_per_minute)
    return InstrumentedLLM(limited, provider=spec.name)


@lru_cache
def get_stt() -> SpeechToTextPort:
    settings = get_settings()
    return require_spec("stt", settings.stt_provider).build(settings)  # type: ignore[no-any-return]


@lru_cache
def get_tts() -> TextToSpeechPort:
    settings = get_settings()
    return require_spec("tts", settings.tts_provider).build(settings)  # type: ignore[no-any-return]


@lru_cache
def get_storage() -> BlobStore:
    settings = get_settings()
    return require_spec("storage", settings.storage_provider).build(settings)  # type: ignore[no-any-return]


# --- engine, workflow --------------------------------------------------------


@lru_cache
def get_pipeline() -> TurnPipeline:
    return TurnPipeline(get_llm())


@lru_cache
def get_step_records() -> StepRecordStore:
    # SQL-backed for every real deployment (inline or redis): a redis worker
    # is a separate process from whoever enqueued the run, and an in-memory
    # store would not survive that boundary. Tests override this with
    # `InMemoryStepRecordStore` via `app.dependency_overrides`.
    return SqlStepRecordStore(get_session_factory())


@lru_cache
def get_workflow_engine() -> WorkflowEngine:
    settings = get_settings()
    turn_steps = build_turn_steps(
        storage=get_storage(),
        stt=get_stt(),
        tts=get_tts(),
        pipeline=get_pipeline(),
        personas=get_persona_repo(),
        sessions=get_session_repo(),
        turns=get_turn_repo(),
        artifacts=get_artifact_repo(),
        clock=get_clock(),
        ids=get_ids(),
    )
    evaluation_steps = build_evaluation_steps(
        llm=get_llm(),
        personas=get_persona_repo(),
        sessions=get_session_repo(),
        turns=get_turn_repo(),
        reports=get_report_repo(),
        clock=get_clock(),
        ids=get_ids(),
    )
    spec = require_spec("workflow", settings.workflow_provider)
    engine: WorkflowEngine = spec.build(
        settings,
        workflows={"turn": turn_steps, "evaluation": evaluation_steps},
        run_repo=get_run_repo(),
        records=get_step_records(),
        clock=get_clock(),
        ids=get_ids(),
    )
    return engine


def warm_up() -> None:
    """Builds every provider once, so a bad slug fails at process start,
    loud, naming it -- not at the first turn with a candidate waiting."""
    get_workflow_engine()


# --- background runs ---------------------------------------------------------

_background_log = get_logger("interviewer_api.background")
_tasks: set[asyncio.Task[Any]] = set()


def spawn(label: str, coro: Awaitable[Any]) -> None:
    """Fire-and-forget a coroutine, keeping a strong reference so it is not
    garbage-collected mid-flight, and logging (never raising back into the
    caller) if it fails outside `WorkflowEngine`'s own failure bookkeeping."""

    async def _run() -> None:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 -- last-resort log, run row already marked failed
            _background_log.error("background_task_failed", label=label, error=str(exc))

    task = asyncio.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# --- auth dependencies --------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def require_role(role: str) -> Callable[..., Awaitable[TokenClaims]]:
    """A permission dependency factory: `Depends(require_role("admin"))` is
    introspectable (its `role` is a closure variable, not a magic string
    repeated per router) and every call site shares the same singleton
    through the module-level `require_admin` below."""

    async def _dep(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        settings: Settings = Depends(get_settings),
        clock: Clock = Depends(get_clock),
    ) -> TokenClaims:
        if creds is None:
            raise unauthorized()
        claims = decode_token(creds.credentials, secret=settings.auth_secret_key, now=clock.now())
        if claims.role != role:
            raise forbidden(f"{role} role required")
        return claims

    return _dep


require_admin = require_role("admin")


async def require_candidate_session(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    sessions: SessionRepository = Depends(get_session_repo),
) -> Session:
    """Resolves a candidate token straight into the session it is scoped
    to -- every `/session/*` handler receives the one session it may touch,
    with no id in the URL to check, forget, or tamper with."""
    if creds is None:
        raise unauthorized()
    claims = decode_token(creds.credentials, secret=settings.auth_secret_key, now=clock.now())
    if claims.role != "candidate":
        raise forbidden("candidate role required")
    session = await sessions.get(claims.subject)
    if session is None:
        raise unauthorized("session no longer exists")
    return session


@lru_cache
def get_passkey_lockout() -> PasskeyLockout:
    settings = get_settings()
    return PasskeyLockout(
        max_attempts=settings.passkey_max_attempts, lockout_minutes=settings.passkey_lockout_minutes
    )
