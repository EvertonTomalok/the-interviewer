"""Assertions shared by both the in-memory and the SQL contract runs.

Each function takes already-constructed repository instances and a couple of
factory callables so both backends exercise identical scenarios."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from interviewer_core.domain import (
    InterviewInvite,
    InterviewReport,
    Persona,
    PersonaQuestion,
    QuestionCoverage,
    QuestionScore,
    Session,
    Turn,
    WorkflowRun,
    advance,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_persona(**overrides: Any) -> Persona:
    base: dict[str, Any] = {
        "id": "persona-1",
        "area_id": "area-1",
        "name": "Backend",
        "version": 1,
        "status": "published",
        "language": "en",
        "voice": None,
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "temperature": 0.4,
        "max_tokens": 800,
        "timeout_seconds": 60,
        "greeting_text": "Hi there — café?",
        "intake_prompt_text": "What's your name?",
        "farewell_text": "Thanks, bye",
        "questions": (
            PersonaQuestion(
                ref="q1",
                topic="basics",
                text="Tell me about X",
                expected_answer="mentions Y",
                weight=2.0,
                follow_up_depth=1,
            ),
        ),
        "policy": "guided",
        "min_coverage": 1.0,
        "max_questions": 8,
        "rubric": "score 0-1 per question",
        "created_at": NOW,
    }
    base.update(overrides)
    return Persona(**base)


def make_invite(**overrides: Any) -> InterviewInvite:
    base: dict[str, Any] = {
        "id": "invite-1",
        "slug": "abc123",
        "persona_id": "persona-1",
        "passkey_hash": "$2b$hashed",
        "expires_at": NOW + timedelta(days=7),
        "max_sessions": 1,
        "used_count": 0,
        "status": "active",
        "created_at": NOW,
    }
    base.update(overrides)
    return InterviewInvite(**base)


def make_session(**overrides: Any) -> Session:
    base: dict[str, Any] = {
        "id": "session-1",
        "invite_id": "invite-1",
        "persona_id": "persona-1",
        "phase": "intake",
        "candidate_name": None,
        "name_confidence": None,
        "coverage": {"q1": QuestionCoverage()},
        "started_at": NOW,
        "ended_at": None,
    }
    base.update(overrides)
    return Session(**base)


def make_turn(**overrides: Any) -> Turn:
    base: dict[str, Any] = {
        "id": "turn-1",
        "session_id": "session-1",
        "index": 0,
        "kind": "intake",
        "question_ref": None,
        "transcript": "hello",
        "audio_artifact_id": None,
        "usage": {"tokens": 10},
        "created_at": NOW,
    }
    base.update(overrides)
    return Turn(**base)


def make_run(**overrides: Any) -> WorkflowRun:
    base: dict[str, Any] = {
        "id": "run-1",
        "workflow": "turn",
        "idempotency_key": "session-1:0",
        "status": "queued",
        "input": {"foo": "bar"},
        "error": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return WorkflowRun(**base)


def make_report(**overrides: Any) -> InterviewReport:
    base: dict[str, Any] = {
        "id": "report-1",
        "session_id": "session-1",
        "persona_id": "persona-1",
        "scores": (QuestionScore(question_ref="q1", score=0.8, verdict="pass", rationale="ok"),),
        "overall_score": 0.8,
        "summary": "did well",
        "created_at": NOW,
    }
    base.update(overrides)
    return InterviewReport(**base)


class Repos:
    """Namespace of repository instances for one backend."""

    def __init__(self, **repos: Any) -> None:
        self.__dict__.update(repos)


async def assert_persona_versioning_and_round_trip(
    repos: Repos, duplicate_error: type[Exception]
) -> None:
    v1 = make_persona(version=1)
    await repos.persona.add(v1)

    v2 = make_persona(id="persona-1-v2", version=2)
    await repos.persona.add(v2)

    got_v1 = await repos.persona.get(v1.id)
    assert got_v1 is not None
    assert got_v1.version == 1
    assert got_v1.greeting_text == v1.greeting_text
    assert got_v1.questions[0].expected_answer == "mentions Y"
    assert got_v1.questions[0].weight == 2.0
    assert got_v1.questions[0].follow_up_depth == 1
    assert type(got_v1) is Persona

    with pytest.raises(duplicate_error):
        await repos.persona.add(make_persona(id="persona-1-dup", version=1))


async def assert_turn_ordering_and_uniqueness(
    repos: Repos, duplicate_error: type[Exception]
) -> None:
    await repos.turn.add(make_turn(id="t0", index=0))
    await repos.turn.add(make_turn(id="t2", index=2))
    await repos.turn.add(make_turn(id="t1", index=1))

    turns = await repos.turn.list_for_session("session-1")
    assert [t.index for t in turns] == [0, 1, 2]

    with pytest.raises(duplicate_error):
        await repos.turn.add(make_turn(id="t0-dup", index=0))


async def assert_session_round_trip_and_phase_persists(repos: Repos) -> None:
    session = make_session()
    await repos.session.add(session)

    got = await repos.session.get(session.id)
    assert got is not None
    assert type(got) is Session
    assert got.phase == "intake"

    advanced = advance(got, "register_name")
    advanced = replace(advanced, candidate_name="Ada")
    await repos.session.update(advanced)

    reread = await repos.session.get(session.id)
    assert reread is not None
    assert reread.phase == "questioning"
    assert reread.candidate_name == "Ada"


async def assert_invite_claim_reasons(repos: Repos) -> None:
    await repos.invite.add(
        make_invite(id="inv-expired", slug="expired-1", expires_at=NOW - timedelta(days=1))
    )
    await repos.invite.add(make_invite(id="inv-retired", slug="retired-1", status="retired"))
    await repos.invite.add(
        make_invite(id="inv-exhausted", slug="exhausted-1", max_sessions=1, used_count=1)
    )
    await repos.invite.add(make_invite(id="inv-open", slug="open-1"))

    assert await repos.invite.claim("expired-1", NOW) is None
    assert await repos.invite.claim("retired-1", NOW) is None
    assert await repos.invite.claim("exhausted-1", NOW) is None

    claimed = await repos.invite.claim("open-1", NOW)
    assert claimed is not None
    assert claimed.used_count == 1


async def assert_invite_claim_under_contention(
    repos_factory: Callable[[], Awaitable[Repos]],
) -> None:
    repos = await repos_factory()
    await repos.invite.add(make_invite(slug="contended", max_sessions=1, used_count=0))

    results = await asyncio.gather(
        repos.invite.claim("contended", NOW),
        repos.invite.claim("contended", NOW),
    )
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert winners[0].used_count == 1


async def assert_report_upsert_on_session(repos: Repos, duplicate_error: type[Exception]) -> None:
    await repos.report.add(make_report())
    await repos.report.add(make_report(overall_score=0.5, summary="replayed"))

    got = await repos.report.get_for_session("session-1")
    assert got is not None
    assert got.overall_score == 0.5
    assert got.summary == "replayed"


async def assert_run_idempotency_key_is_unique(
    repos: Repos, duplicate_error: type[Exception]
) -> None:
    await repos.run.add(make_run())
    with pytest.raises(duplicate_error):
        await repos.run.add(make_run(id="run-2"))

    got = await repos.run.get_by_idempotency_key("session-1:0")
    assert got is not None
    assert got.status == "queued"

    updated = replace(got, status="succeeded")
    await repos.run.update(updated)
    reread = await repos.run.get(got.id)
    assert reread is not None
    assert reread.status == "succeeded"


async def assert_absent_ids_return_none(repos: Repos) -> None:
    assert await repos.session.get("missing") is None
    assert await repos.persona.get("missing") is None
    assert await repos.run.get("missing") is None
    assert await repos.report.get_for_session("missing") is None
