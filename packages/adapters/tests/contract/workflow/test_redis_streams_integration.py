"""Integration suite for `redis_streams`, against a real Redis and a real
Postgres (`docker compose up postgres redis`) -- the `integration` marker
keeps this out of `make check`'s fast, container-free loop; run it with
`make itest` or directly:
`pytest -m integration packages/adapters/tests/contract/workflow/test_redis_streams_integration.py`.

This does not re-run the full `inline` contract suite against `redis` --
that would mean re-deriving every assertion around an asynchronous
enqueue/drain split `inline` does not have. It covers what is
`redis_streams`-specific instead: a real turn completing end to end through
`consume_once()`, a crashed consumer's lease reclaimed by another
(PRD §12.4's drill), and a permanent failure landing in the `:dlq` stream.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis, from_url
from sqlmodel import SQLModel

from interviewer_adapters.llm.fake import FakeLLM
from interviewer_adapters.persistence.repositories import (
    SqlArtifactRepository,
    SqlPersonaRepository,
    SqlReportRepository,
    SqlRunRepository,
    SqlSessionRepository,
    SqlTurnRepository,
)
from interviewer_adapters.persistence.session import make_engine, make_session_factory
from interviewer_adapters.persistence.tables import (  # noqa: F401  (populate metadata)
    AreaTable,
    ArtifactTable,
    InterviewInviteTable,
    InterviewReportTable,
    PersonaTable,
    SessionTable,
    TurnTable,
    UserTable,
    WorkflowRunTable,
    WorkflowStepRecordTable,
)
from interviewer_adapters.speech.fake_stt import FakeSTT
from interviewer_adapters.speech.tts_none import NoneTTS
from interviewer_adapters.storage.in_memory import InMemoryBlobStore
from interviewer_adapters.workflow import build_turn_steps
from interviewer_adapters.workflow.redis_streams import RedisStreamsWorkflowEngine
from interviewer_adapters.workflow.sql_step_records import SqlStepRecordStore
from interviewer_core.engine import TurnPipeline
from interviewer_core.errors import PortError
from interviewer_core.ports.clock import SystemClock
from interviewer_core.ports.ids import SeqIds

from .conftest import intake_and_two_questions_answers, make_persona, make_session

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://interviewer:interviewer@localhost:5433/interviewer",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380/0")


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = from_url(REDIS_URL, decode_responses=True)
    yield client
    async for key in client.scan_iter(match="workflow:*"):
        await client.delete(key)
    await client.aclose()


@pytest.fixture
async def sql_stack() -> AsyncIterator[dict[str, object]]:
    engine = make_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = make_session_factory(engine)

    yield {
        "personas": SqlPersonaRepository(factory),
        "sessions": SqlSessionRepository(factory),
        "turns": SqlTurnRepository(factory),
        "artifacts": SqlArtifactRepository(factory),
        "reports": SqlReportRepository(factory),
        "run_repo": SqlRunRepository(factory),
        "records": SqlStepRecordStore(factory),
    }

    async with engine.begin() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            await conn.execute(table.delete())
    await engine.dispose()


def _engine(sql_stack: dict[str, object], redis_client: Redis, *, answers=None, fail_at=None):
    llm = FakeLLM(answers=list(answers or []))
    storage = InMemoryBlobStore()
    steps = build_turn_steps(
        storage=storage,
        stt=FakeSTT(),
        tts=NoneTTS(),
        pipeline=TurnPipeline(llm),
        personas=sql_stack["personas"],
        sessions=sql_stack["sessions"],
        turns=sql_stack["turns"],
        artifacts=sql_stack["artifacts"],
        clock=SystemClock(),
        ids=SeqIds(prefix=uuid.uuid4().hex[:8]),
    )
    engine = RedisStreamsWorkflowEngine(
        {"turn": steps},
        redis=redis_client,
        run_repo=sql_stack["run_repo"],
        records=sql_stack["records"],
        clock=SystemClock(),
        ids=SeqIds(prefix=uuid.uuid4().hex[:8]),
        visibility_timeout_seconds=0.2,
        fail_at=fail_at,
    )
    return engine, storage


async def test_full_turn_round_trip_through_consume_once(sql_stack, redis_client) -> None:
    engine, storage = _engine(sql_stack, redis_client, answers=intake_and_two_questions_answers())
    persona = make_persona(id=f"p-{uuid.uuid4().hex[:8]}")
    session = make_session(persona, id=f"s-{uuid.uuid4().hex[:8]}")
    await sql_stack["personas"].add(persona)
    await sql_stack["sessions"].add(session)
    await storage.put(f"staging/{session.id}/0", b"audio", mime="audio/wav")

    payload = {
        "session_id": session.id,
        "persona_id": persona.id,
        "turn_index": 0,
        "staging_uri": f"memory://staging/{session.id}/0",
        "mime": "audio/wav",
        "language": None,
        "reply_mode": "text",
        "voice": None,
        "format": "wav",
    }
    handle = await engine.start("turn", payload, idempotency_key=f"{session.id}:0")

    # nothing runs until a worker drains the stream
    state = await engine.status(handle.run_id)
    assert state.status == "running"

    for _ in range(3):
        await engine.consume_once("turn", block_ms=200)

    state = await engine.status(handle.run_id)
    assert state.status == "succeeded"

    turns = await sql_stack["turns"].list_for_session(session.id)
    assert [t.index for t in turns] == [0, 1]


async def test_crashed_consumer_lease_is_reclaimed_by_another(sql_stack, redis_client) -> None:
    crashing, storage = _engine(
        sql_stack,
        redis_client,
        answers=intake_and_two_questions_answers(),
        fail_at=lambda name, attempt: name == "compose" and attempt == 1,
    )
    persona = make_persona(id=f"p-{uuid.uuid4().hex[:8]}")
    session = make_session(persona, id=f"s-{uuid.uuid4().hex[:8]}")
    await sql_stack["personas"].add(persona)
    await sql_stack["sessions"].add(session)
    await storage.put(f"staging/{session.id}/0", b"audio", mime="audio/wav")

    payload = {
        "session_id": session.id,
        "persona_id": persona.id,
        "turn_index": 0,
        "staging_uri": f"memory://staging/{session.id}/0",
        "mime": "audio/wav",
        "language": None,
        "reply_mode": "text",
        "voice": None,
        "format": "wav",
    }
    handle = await crashing.start("turn", payload, idempotency_key=f"{session.id}:0")

    # this consumer dies partway through -- persist_audio and transcribe
    # succeed and checkpoint; compose never returns, so the entry is never
    # acked.
    await crashing.consume_once("turn", consumer="doomed-worker", block_ms=200)
    state = await crashing.status(handle.run_id)
    assert state.status == "running"

    await asyncio.sleep(0.3)  # past the 0.2s visibility timeout

    # a second worker, sharing the same Redis/Postgres, reclaims the lease
    survivor, _ = _engine(sql_stack, redis_client, answers=intake_and_two_questions_answers())
    for _ in range(3):
        await survivor.consume_once("turn", consumer="survivor-worker", block_ms=200)

    state = await survivor.status(handle.run_id)
    assert state.status == "succeeded"

    turns = await sql_stack["turns"].list_for_session(session.id)
    assert [t.index for t in turns] == [0, 1]  # no duplicate turn from the reclaim


async def test_permanent_failure_lands_in_dlq(sql_stack, redis_client) -> None:
    class BrokenStorage:
        async def put(self, key, content, *, mime):
            raise PortError("bucket gone", transient=False)

        async def get(self, uri):
            raise PortError("bucket gone", transient=False)

        async def signed_url(self, uri, *, expires_in_seconds):
            raise PortError("bucket gone", transient=False)

    llm = FakeLLM(answers=intake_and_two_questions_answers())
    steps = build_turn_steps(
        storage=BrokenStorage(),
        stt=FakeSTT(),
        tts=NoneTTS(),
        pipeline=TurnPipeline(llm),
        personas=sql_stack["personas"],
        sessions=sql_stack["sessions"],
        turns=sql_stack["turns"],
        artifacts=sql_stack["artifacts"],
        clock=SystemClock(),
        ids=SeqIds(),
    )
    engine = RedisStreamsWorkflowEngine(
        {"turn": steps},
        redis=redis_client,
        run_repo=sql_stack["run_repo"],
        records=sql_stack["records"],
        clock=SystemClock(),
        ids=SeqIds(prefix=uuid.uuid4().hex[:8]),
        visibility_timeout_seconds=0.2,
    )

    persona = make_persona(id=f"p-{uuid.uuid4().hex[:8]}")
    session = make_session(persona, id=f"s-{uuid.uuid4().hex[:8]}")
    await sql_stack["personas"].add(persona)
    await sql_stack["sessions"].add(session)

    payload = {
        "session_id": session.id,
        "persona_id": persona.id,
        "turn_index": 0,
        "staging_uri": "memory://missing",
        "mime": "audio/wav",
        "language": None,
        "reply_mode": "text",
        "voice": None,
        "format": "wav",
    }
    handle = await engine.start("turn", payload, idempotency_key=f"{session.id}:0")
    await engine.consume_once("turn", block_ms=200)

    state = await engine.status(handle.run_id)
    assert state.status == "failed"
    assert state.error is not None
    assert "persist_audio" in state.error

    dlq_entries = await redis_client.xrange("workflow:turn:dlq")
    assert any(fields.get("run_id") == handle.run_id for _id, fields in dlq_entries)
