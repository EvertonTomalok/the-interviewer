"""Shared fixtures for the workflow contract suite.

Every persona question's `expected_answer` is `"fake"` on purpose: the real
`TranscribeStep` runs against the real `FakeSTT`, whose transcript is
`"[fake transcript <hash>]"` -- always containing the word "fake" -- so
`assess_answer()` scores every answer at full confidence with no need to
control what the (unpredictable, hash-derived) transcript text actually
says.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from interviewer_adapters.llm.fake import FakeLLM
from interviewer_adapters.speech.fake_stt import FakeSTT
from interviewer_adapters.speech.fake_tts import FakeTTS
from interviewer_adapters.speech.tts_none import NoneTTS
from interviewer_adapters.storage.in_memory import InMemoryBlobStore
from interviewer_adapters.workflow import (
    BaseStep,
    InlineWorkflowEngine,
    InMemoryStepRecordStore,
    build_evaluation_steps,
    build_turn_steps,
)
from interviewer_adapters.workflow.inline import FailHook
from interviewer_core.domain.entities import (
    Persona,
    PersonaQuestion,
    QuestionCoverage,
    Session,
)
from interviewer_core.engine import TurnPipeline
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import SeqIds
from interviewer_core.ports.llm import LLMAnswer, LLMUsage

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _StepClock:
    """`FrozenClock`-shaped, but real enough to advance per `now()` call so
    every `created_at`/`updated_at` in a test is distinct and ordered."""

    _now: datetime = NOW

    def now(self) -> datetime:
        current = self._now
        self._now = current.replace(microsecond=(current.microsecond + 1) % 1_000_000)
        return current


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
        "max_tokens": 200,
        "timeout_seconds": 60,
        "greeting_text": "Hi there, ready to start?",
        "intake_prompt_text": "What is your name?",
        "farewell_text": "Thanks so much, that is everything.",
        "questions": (
            PersonaQuestion(
                ref="q1", topic="one", text="First question fallback?", expected_answer="fake"
            ),
            PersonaQuestion(
                ref="q2", topic="two", text="Second question fallback?", expected_answer="fake"
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


def make_session(persona: Persona, **overrides: Any) -> Session:
    base: dict[str, Any] = {
        "id": "session-1",
        "invite_id": "invite-1",
        "persona_id": persona.id,
        "phase": "intake",
        "candidate_name": None,
        "name_confidence": None,
        "coverage": {q.ref: QuestionCoverage() for q in persona.questions},
        "started_at": NOW,
        "ended_at": None,
    }
    base.update(overrides)
    return Session(**base)


def intake_and_two_questions_answers() -> list[LLMAnswer]:
    """Scripted for `make_persona()`'s default two-question guided persona:
    1 intake extraction + 1 compose per question, 0 for closing (scripted
    text, no model call)."""
    zero = LLMUsage(prompt_tokens=0, completion_tokens=0)
    return [
        LLMAnswer(text='{"name": "Ada Lovelace"}', usage=zero),
        LLMAnswer(text="What is the first thing you want to tell me?", usage=zero),
        LLMAnswer(text="What is the second thing on your mind?", usage=zero),
    ]


class Rig:
    """One fully-wired stack: repos, fakes, and an `InlineWorkflowEngine`
    with both workflows registered."""

    def __init__(
        self,
        *,
        answers: Sequence[LLMAnswer] | None = None,
        reply_mode_voice: bool = False,
        fail_at: FailHook | None = None,
        llm: Any = None,
        stt: Any = None,
    ) -> None:
        from interviewer_adapters.persistence.in_memory import (
            InMemoryArtifactRepository,
            InMemoryPersonaRepository,
            InMemoryReportRepository,
            InMemoryRunRepository,
            InMemorySessionRepository,
            InMemoryTurnRepository,
        )

        self.clock: Clock = _StepClock()
        self.ids = SeqIds()
        self.storage = InMemoryBlobStore()
        self.llm = llm if llm is not None else FakeLLM(answers=list(answers or []))
        self.stt = stt if stt is not None else FakeSTT()
        self.tts = FakeTTS() if reply_mode_voice else NoneTTS()

        self.run_repo = InMemoryRunRepository()
        self.records = InMemoryStepRecordStore()
        self.personas = InMemoryPersonaRepository()
        self.sessions = InMemorySessionRepository()
        self.turns = InMemoryTurnRepository()
        self.artifacts = InMemoryArtifactRepository()
        self.reports = InMemoryReportRepository()

        pipeline = TurnPipeline(self.llm)
        turn_steps: tuple[BaseStep, ...] = build_turn_steps(
            storage=self.storage,
            stt=self.stt,
            tts=self.tts,
            pipeline=pipeline,
            personas=self.personas,
            sessions=self.sessions,
            turns=self.turns,
            artifacts=self.artifacts,
            clock=self.clock,
            ids=self.ids,
        )
        eval_steps: tuple[BaseStep, ...] = build_evaluation_steps(
            llm=self.llm,
            personas=self.personas,
            sessions=self.sessions,
            turns=self.turns,
            reports=self.reports,
            clock=self.clock,
            ids=self.ids,
        )
        self.engine = InlineWorkflowEngine(
            {"turn": turn_steps, "evaluation": eval_steps},
            run_repo=self.run_repo,
            records=self.records,
            clock=self.clock,
            ids=self.ids,
            fail_at=fail_at,
        )

    async def seed(self, persona: Persona, session: Session) -> None:
        await self.personas.add(persona)
        await self.sessions.add(session)

    async def stage_upload(
        self, session_id: str, turn_index: int, content: bytes = b"audio"
    ) -> str:
        key = f"staging/{session_id}/{turn_index}"
        return await self.storage.put(key, content, mime="audio/wav")

    def turn_payload(
        self,
        *,
        session_id: str,
        persona_id: str,
        turn_index: int,
        staging_uri: str,
        reply_mode: str = "text",
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "persona_id": persona_id,
            "turn_index": turn_index,
            "staging_uri": staging_uri,
            "mime": "audio/wav",
            "language": None,
            "reply_mode": reply_mode,
            "voice": None,
            "format": "wav",
        }
