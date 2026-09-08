"""Everything every test in this package shares: a fully wired app (every
port a fake or an in-memory repository, `WORKFLOW_PROVIDER=inline`) behind
`app.dependency_overrides`, and small helpers for the flows every test
walks through -- register an admin, publish a persona, claim an invite,
poll a run to a terminal status.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from interviewer_adapters.llm.fake import FakeLLM
from interviewer_adapters.persistence import (
    InMemoryAreaRepository,
    InMemoryArtifactRepository,
    InMemoryInviteRepository,
    InMemoryPersonaRepository,
    InMemoryReportRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTurnRepository,
    InMemoryUserRepository,
)
from interviewer_adapters.speech.fake_stt import FakeSTT
from interviewer_adapters.speech.fake_tts import FakeTTS
from interviewer_adapters.storage.in_memory import InMemoryBlobStore
from interviewer_adapters.workflow.base import InMemoryStepRecordStore
from interviewer_adapters.workflow.evaluation_steps import build_evaluation_steps
from interviewer_adapters.workflow.inline import InlineWorkflowEngine
from interviewer_adapters.workflow.turn_steps import build_turn_steps
from interviewer_api import deps
from interviewer_api.main import app
from interviewer_api.passkeys import PasskeyLockout
from interviewer_core.config import Settings
from interviewer_core.engine import TurnPipeline
from interviewer_core.ports.clock import FrozenClock
from interviewer_core.ports.ids import SeqIds
from interviewer_core.ports.llm import LLMAnswer, LLMUsage

_USAGE = LLMUsage(prompt_tokens=1, completion_tokens=1)


def answer(text: str) -> LLMAnswer:
    return LLMAnswer(text=text, usage=_USAGE)


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://test/test",
        "redis_url": "redis://test",
        "auth_secret_key": "test-secret-key",
        "workflow_provider": "inline",
        "reply_mode": "text",
        "tts_provider": "none",
        "registration_open": True,
        "passkey_max_attempts": 3,
        "passkey_lockout_minutes": 15,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class Graph:
    """One process's worth of fakes -- everything a test can reach into
    directly, and everything the app's `Depends()`s are overridden with."""

    def __init__(self, *, llm: Any = None, stt: Any = None, **setting_overrides: object) -> None:
        self.settings = make_settings(**setting_overrides)
        self.clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
        self.ids = SeqIds()

        self.users = InMemoryUserRepository()
        self.areas = InMemoryAreaRepository()
        self.personas = InMemoryPersonaRepository()
        self.invites = InMemoryInviteRepository()
        self.sessions = InMemorySessionRepository()
        self.turns = InMemoryTurnRepository()
        self.artifacts = InMemoryArtifactRepository()
        self.reports = InMemoryReportRepository()
        self.runs = InMemoryRunRepository()

        # A caller that needs a broken/scripted `LLMPort` (e.g. to prove a
        # route returns 202 even when the provider fails) passes `llm=`
        # here -- overriding `deps.get_llm` after construction would not
        # reach it: the workflow's steps hold a direct reference to
        # `self.pipeline`, wired once, below, not resolved through
        # `Depends()` on every call.
        self.llm = llm if llm is not None else FakeLLM()
        self.stt = stt if stt is not None else FakeSTT()
        self.tts = FakeTTS()
        self.storage = InMemoryBlobStore()
        self.records = InMemoryStepRecordStore()
        self.pipeline = TurnPipeline(self.llm)
        self.lockout = PasskeyLockout(
            max_attempts=self.settings.passkey_max_attempts,
            lockout_minutes=self.settings.passkey_lockout_minutes,
        )

        turn_steps = build_turn_steps(
            storage=self.storage,
            stt=self.stt,
            tts=self.tts,
            pipeline=self.pipeline,
            personas=self.personas,
            sessions=self.sessions,
            turns=self.turns,
            artifacts=self.artifacts,
            clock=self.clock,
            ids=self.ids,
        )
        evaluation_steps = build_evaluation_steps(
            llm=self.llm,
            personas=self.personas,
            sessions=self.sessions,
            turns=self.turns,
            reports=self.reports,
            clock=self.clock,
            ids=self.ids,
        )
        self.engine = InlineWorkflowEngine(
            {"turn": turn_steps, "evaluation": evaluation_steps},
            run_repo=self.runs,
            records=self.records,
            clock=self.clock,
            ids=self.ids,
        )

    def script(self, *texts: str) -> None:
        """Queue raw-text answers onto the shared `FakeLLM`."""
        self.llm._answers.extend(answer(t) for t in texts)  # noqa: SLF001 -- test-only access


class _FakeDbSession:
    async def __aenter__(self) -> _FakeDbSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, *args: object, **kwargs: object) -> None:
        return None


def _fake_session_factory() -> _FakeDbSession:
    return _FakeDbSession()


@pytest.fixture
def graph() -> Graph:
    return Graph()


@pytest.fixture
def graph_factory() -> Any:
    """The `Graph` class itself, for a test that needs a custom instance
    (e.g. `graph_factory(llm=broken)`) instead of the shared `graph`."""
    return Graph


def _apply_overrides(graph: Graph) -> None:
    app.dependency_overrides[deps.get_settings] = lambda: graph.settings
    app.dependency_overrides[deps.get_clock] = lambda: graph.clock
    app.dependency_overrides[deps.get_ids] = lambda: graph.ids
    app.dependency_overrides[deps.get_user_repo] = lambda: graph.users
    app.dependency_overrides[deps.get_area_repo] = lambda: graph.areas
    app.dependency_overrides[deps.get_persona_repo] = lambda: graph.personas
    app.dependency_overrides[deps.get_invite_repo] = lambda: graph.invites
    app.dependency_overrides[deps.get_session_repo] = lambda: graph.sessions
    app.dependency_overrides[deps.get_turn_repo] = lambda: graph.turns
    app.dependency_overrides[deps.get_artifact_repo] = lambda: graph.artifacts
    app.dependency_overrides[deps.get_report_repo] = lambda: graph.reports
    app.dependency_overrides[deps.get_run_repo] = lambda: graph.runs
    app.dependency_overrides[deps.get_llm] = lambda: graph.llm
    app.dependency_overrides[deps.get_stt] = lambda: graph.stt
    app.dependency_overrides[deps.get_tts] = lambda: graph.tts
    app.dependency_overrides[deps.get_storage] = lambda: graph.storage
    app.dependency_overrides[deps.get_pipeline] = lambda: graph.pipeline
    app.dependency_overrides[deps.get_step_records] = lambda: graph.records
    app.dependency_overrides[deps.get_workflow_engine] = lambda: graph.engine
    app.dependency_overrides[deps.get_passkey_lockout] = lambda: graph.lockout
    app.dependency_overrides[deps.get_session_factory] = lambda: _fake_session_factory


@pytest.fixture
def apply_overrides() -> Any:
    """For a test that needs its own `Graph` (e.g. one built with a broken
    `llm=`) instead of the shared `graph`/`client` fixtures."""
    return _apply_overrides


@pytest.fixture
async def client(graph: Graph) -> AsyncIterator[httpx.AsyncClient]:
    _apply_overrides(graph)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


async def _poll_run(
    client: httpx.AsyncClient, headers: dict[str, str], run_id: str, *, max_attempts: int = 200
) -> dict[str, Any]:
    """Polls `GET /session/runs/{id}` to a terminal status -- the same shape
    a real client polls, and the only reliable way to wait on a background
    task spawned onto the same event loop as the test."""
    for _ in range(max_attempts):
        response = await client.get(f"/session/runs/{run_id}", headers=headers)
        data: dict[str, Any] = response.json()["data"]
        if data["status"] in ("succeeded", "failed"):
            return data
        await asyncio.sleep(0)
    raise AssertionError(f"run {run_id!r} did not reach a terminal status")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(
    client: httpx.AsyncClient, *, email: str = "admin@example.com"
) -> str:
    await client.post("/auth/register", json={"email": email, "password": "hunter2hunter"})
    response = await client.post("/auth/login", json={"email": email, "password": "hunter2hunter"})
    token: str = response.json()["data"]["access_token"]
    return token


async def _publish_area_and_persona(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    max_questions: int = 1,
    min_coverage: float = 0.99,
    questions: list[dict[str, object]] | None = None,
) -> dict[str, str]:
    headers = _auth_header(admin_token)
    area_resp = await client.post(
        "/areas", json={"slug": "backend", "name": "Backend"}, headers=headers
    )
    area_id = area_resp.json()["data"]["id"]

    persona_body = {
        "name": "Backend v1",
        "version": 1,
        "language": "en",
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "greeting_text": "Welcome to the interview!",
        "intake_prompt_text": "Sorry, could you say your name again?",
        "farewell_text": "Thanks, that's everything from me.",
        "questions": questions
        or [
            {
                "ref": "q1",
                "topic": "backend",
                "text": "Tell me about a challenge you solved.",
                "expected_answer": "mentions a concrete fix",
            }
        ],
        "policy": "guided",
        "min_coverage": min_coverage,
        "max_questions": max_questions,
        "rubric": "score 0-1 per question",
    }
    persona_resp = await client.post(
        f"/areas/{area_id}/personas", json=persona_body, headers=headers
    )
    persona_id = persona_resp.json()["data"]["id"]

    invite_resp = await client.post("/invites", json={"persona_id": persona_id}, headers=headers)
    invite_data = invite_resp.json()["data"]
    return {
        "area_id": area_id,
        "persona_id": persona_id,
        "invite_id": invite_data["id"],
        "slug": invite_data["slug"],
        "passkey": invite_data["passkey"],
    }


# --- fixtures wrapping the helpers above -------------------------------
#
# Plain functions, not classes, so a test file gets them as ordinary
# callables (`poll_run(client, ...)`) -- fixtures only because this test
# tree has no `tests/__init__.py`, so a cross-file `import` would not
# resolve reliably under `--import-mode=importlib`.


@pytest.fixture
def auth_header() -> Any:
    return _auth_header


@pytest.fixture
def register_and_login() -> Any:
    return _register_and_login


@pytest.fixture
def publish_area_and_persona() -> Any:
    return _publish_area_and_persona


@pytest.fixture
def poll_run() -> Any:
    return _poll_run
