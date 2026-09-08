"""The worker's own composition root -- the same object graph as
`interviewer_api.deps`, minus everything HTTP-only (auth, passkeys). Kept
separate on purpose: this process has no routes and no bearer tokens, and a
change to one app's graph should not force a read of the other's.
"""

from __future__ import annotations

from functools import lru_cache

import interviewer_adapters  # noqa: F401 -- import side effect: registers every provider
from interviewer_adapters.llm.decorators import InstrumentedLLM, RateLimitedLLM, RetryingLLM
from interviewer_adapters.persistence import (
    SessionFactory,
    SqlArtifactRepository,
    SqlPersonaRepository,
    SqlReportRepository,
    SqlRunRepository,
    SqlSessionRepository,
    SqlTurnRepository,
    make_engine,
    make_session_factory,
)
from interviewer_adapters.workflow.evaluation_steps import build_evaluation_steps
from interviewer_adapters.workflow.sql_step_records import SqlStepRecordStore
from interviewer_adapters.workflow.turn_steps import build_turn_steps
from interviewer_core.config import Settings, load_settings
from interviewer_core.engine import TurnPipeline
from interviewer_core.ports.clock import Clock, SystemClock
from interviewer_core.ports.ids import IdGenerator, Uuid7Ids
from interviewer_core.ports.llm import LLMPort
from interviewer_core.ports.repositories import (
    ArtifactRepository,
    PersonaRepository,
    ReportRepository,
    RunRepository,
    SessionRepository,
    TurnRepository,
)
from interviewer_core.ports.speech import SpeechToTextPort, TextToSpeechPort
from interviewer_core.ports.storage import BlobStore
from interviewer_core.ports.workflow import WorkflowEngine
from interviewer_core.registry import require_spec


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@lru_cache
def get_clock() -> Clock:
    return SystemClock()


@lru_cache
def get_ids() -> IdGenerator:
    return Uuid7Ids()


@lru_cache
def get_session_factory() -> SessionFactory:
    return make_session_factory(make_engine(get_settings().database_url))


@lru_cache
def get_persona_repo() -> PersonaRepository:
    return SqlPersonaRepository(get_session_factory())


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


@lru_cache
def get_pipeline() -> TurnPipeline:
    return TurnPipeline(get_llm())


@lru_cache
def get_step_records() -> SqlStepRecordStore:
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
