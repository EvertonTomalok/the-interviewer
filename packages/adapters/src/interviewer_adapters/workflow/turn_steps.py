"""The five steps of PRD §5.4: `persist_audio -> transcribe -> compose ->
synthesize -> commit_turn`. One workflow for every phase -- intake and a
question round run the exact same five steps; only what `compose` returns
differs.

**Row convention** (not in the frozen domain, decided here): a round's two
`Turn` rows share no explicit speaker field, so `commit_turn` assigns them
by index parity off `ctx.input["turn_index"]` (n, 0-based): the candidate's
reply is `2n`, the interviewer's output is `2n + 1`. `build_history`
reconstructs `HistoryTurn`s from that convention: a completed round pairs
an interviewer row with the candidate row that answered it, and the most
recently asked question -- not yet answered by a persisted candidate row,
because that is exactly what the in-flight round is about to write --
still gets its own trailing entry with an empty `candidate_text`, which is
what lets `TurnPipeline._run_questioning` find *which* question the fresh
reply is answering. The candidate's very first utterance (answering the
unstored greeting) produces no history entry, matching `TurnPipeline`'s own
expectation of empty history on the true first attempt.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from interviewer_adapters.workflow.base import BaseStep
from interviewer_core.domain.entities import Artifact, QuestionCoverage, Session, Turn, TurnKind
from interviewer_core.engine import TurnOutcome, TurnPipeline, TurnRequest
from interviewer_core.engine.types import HistoryTurn
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.repositories import (
    ArtifactRepository,
    PersonaRepository,
    SessionRepository,
    TurnRepository,
)
from interviewer_core.ports.speech import SpeechToTextPort, TextToSpeechPort
from interviewer_core.ports.storage import BlobStore
from interviewer_core.ports.workflow import StepContext


def build_history(turns: Sequence[Turn]) -> tuple[HistoryTurn, ...]:
    """Reconstructs `HistoryTurn`s the way `TurnPipeline` needs them: a
    *completed* round pairs an interviewer row with the candidate row that
    answered it, but the most recently asked question -- if no candidate
    row has answered it yet -- still gets its own trailing entry, with an
    empty `candidate_text`. `_run_questioning` reads that entry's
    `question_ref` to know what the *current*, in-flight reply is
    answering; it never reads that entry's `candidate_text` (it uses the
    fresh transcript instead), so the placeholder is never seen."""
    history: list[HistoryTurn] = []
    pending: Turn | None = None
    for turn in sorted(turns, key=lambda t: t.index):
        if turn.index % 2 == 1:
            if pending is not None:
                history.append(_pending_entry(pending))
            pending = turn
        elif pending is not None:
            history.append(
                HistoryTurn(
                    kind=pending.kind,
                    question_ref=pending.question_ref,
                    asked_text=pending.transcript or "",
                    candidate_text=turn.transcript or "",
                )
            )
            pending = None
    if pending is not None:
        history.append(_pending_entry(pending))
    return tuple(history)


def _pending_entry(interviewer_turn: Turn) -> HistoryTurn:
    return HistoryTurn(
        kind=interviewer_turn.kind,
        question_ref=interviewer_turn.question_ref,
        asked_text=interviewer_turn.transcript or "",
        candidate_text="",
    )


class PersistAudioStep(BaseStep):
    """Turns the API's staged upload into the durable `Artifact` row.
    Does not upload anything -- the bytes are already at `staging_uri`,
    written by the API inside the request, the only moment they exist."""

    name = "persist_audio"
    max_attempts = 3

    def __init__(
        self, *, storage: BlobStore, artifacts: ArtifactRepository, clock: Clock, ids: IdGenerator
    ) -> None:
        self._storage = storage
        self._artifacts = artifacts
        self._clock = clock
        self._ids = ids

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        uri = str(ctx.input["staging_uri"])
        mime = str(ctx.input["mime"])
        content = await self._storage.get(uri)
        artifact = Artifact(
            id=self._ids.new_id(),
            session_id=str(ctx.input["session_id"]),
            kind="candidate_audio",
            mime=mime,
            size_bytes=len(content),
            uri=uri,
            checksum=hashlib.sha256(content).hexdigest(),
            created_at=self._clock.now(),
        )
        await self._artifacts.add(artifact)
        return {
            "artifact_id": artifact.id,
            "uri": artifact.uri,
            "size_bytes": artifact.size_bytes,
            "checksum": artifact.checksum,
        }


class TranscribeStep(BaseStep):
    name = "transcribe"
    max_attempts = 3

    def __init__(self, *, stt: SpeechToTextPort, storage: BlobStore) -> None:
        self._stt = stt
        self._storage = storage

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        persisted = ctx.outputs["persist_audio"]
        content = await self._storage.get(str(persisted["uri"]))
        language = ctx.input.get("language")
        transcript = await self._stt.transcribe(
            content, mime=str(ctx.input["mime"]), language=str(language) if language else None
        )
        return {"text": transcript.text, "language": transcript.language}


class ComposeStep(BaseStep):
    """Wraps `TurnPipeline.run()` -- route, compose and guard for one round,
    including the phase transition (`advance()`), already happen inside it."""

    name = "compose"
    max_attempts = 2

    def __init__(
        self,
        *,
        pipeline: TurnPipeline,
        personas: PersonaRepository,
        sessions: SessionRepository,
        turns: TurnRepository,
    ) -> None:
        self._pipeline = pipeline
        self._personas = personas
        self._sessions = sessions
        self._turns = turns

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        persona = await self._personas.get(str(ctx.input["persona_id"]))
        if persona is None:
            raise LookupError(f"no persona {ctx.input['persona_id']!r}")
        session = await self._sessions.get(str(ctx.input["session_id"]))
        if session is None:
            raise LookupError(f"no session {ctx.input['session_id']!r}")

        existing_turns = await self._turns.list_for_session(session.id)
        history = build_history(existing_turns)
        candidate_text = str(ctx.outputs["transcribe"]["text"])

        outcome = await self._pipeline.run(
            TurnRequest(
                persona=persona, session=session, history=history, candidate_text=candidate_text
            )
        )
        return _outcome_to_output(outcome)


def _outcome_to_output(outcome: TurnOutcome) -> Mapping[str, Any]:
    return {
        "session_phase": outcome.session.phase,
        "session_candidate_name": outcome.session.candidate_name,
        "session_name_confidence": outcome.session.name_confidence,
        "session_coverage": {
            ref: {"asked": c.asked, "answered": c.answered, "confidence": c.confidence}
            for ref, c in outcome.session.coverage.items()
        },
        "text": outcome.text,
        "kind": outcome.kind,
        "question_ref": outcome.question_ref,
        "ends_session": outcome.ends_session,
        "end_reason": outcome.end_reason,
        "degraded": outcome.degraded,
        "question_number": outcome.question_number,
        "question_total": outcome.question_total,
        "usage": {
            "prompt_tokens": outcome.usage.prompt_tokens,
            "completion_tokens": outcome.usage.completion_tokens,
        },
    }


class SynthesizeStep(BaseStep):
    """`reply_mode` is read once, from `ctx.input`, never from live settings
    -- a flag flipped mid-flight must not change what a replay produces."""

    name = "synthesize"
    max_attempts = 3

    def __init__(
        self, *, tts: TextToSpeechPort, storage: BlobStore, ids: IdGenerator, clock: Clock
    ) -> None:
        self._tts = tts
        self._storage = storage
        self._ids = ids
        self._clock = clock

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        if ctx.input.get("reply_mode") != "voice":
            return {"skipped": True, "reason": "reply_mode=text"}

        text = str(ctx.outputs["compose"]["text"])
        voice = ctx.input.get("voice")
        audio_format = str(ctx.input.get("format") or "wav")
        blob = await self._tts.synthesize(
            text, voice=str(voice) if voice else None, format=audio_format
        )
        key = f"sessions/{ctx.input['session_id']}/replies/{self._ids.new_id()}"
        uri = await self._storage.put(key, blob.content, mime=blob.mime)
        return {
            "skipped": False,
            "uri": uri,
            "mime": blob.mime,
            "size_bytes": len(blob.content),
        }


class CommitTurnStep(BaseStep):
    """Idempotent by construction: `execute()` never calls `run()` twice for
    the same run, so the two `Turn` writes below happen exactly once."""

    name = "commit_turn"
    max_attempts = 3

    def __init__(
        self,
        *,
        sessions: SessionRepository,
        turns: TurnRepository,
        artifacts: ArtifactRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._turns = turns
        self._artifacts = artifacts
        self._clock = clock
        self._ids = ids

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        session = await self._sessions.get(str(ctx.input["session_id"]))
        if session is None:
            raise LookupError(f"no session {ctx.input['session_id']!r}")

        compose = ctx.outputs["compose"]
        turn_index = int(ctx.input["turn_index"])
        candidate_kind: TurnKind = "intake" if session.phase == "intake" else "question"
        last_question_ref = _last_question_ref(await self._turns.list_for_session(session.id))

        candidate_turn = Turn(
            id=self._ids.new_id(),
            session_id=session.id,
            index=turn_index * 2,
            kind=candidate_kind,
            question_ref=last_question_ref,
            transcript=str(ctx.outputs["transcribe"]["text"]),
            audio_artifact_id=str(ctx.outputs["persist_audio"]["artifact_id"]),
            usage={},
            created_at=self._clock.now(),
        )
        await self._turns.add(candidate_turn)

        synth = ctx.outputs.get("synthesize", {})
        interviewer_audio_id: str | None = None
        if not synth.get("skipped", True):
            reply_artifact = Artifact(
                id=self._ids.new_id(),
                session_id=session.id,
                kind="interviewer_audio",
                mime=str(synth["mime"]),
                size_bytes=int(synth["size_bytes"]),
                uri=str(synth["uri"]),
                checksum="",
                created_at=self._clock.now(),
            )
            await self._artifacts.add(reply_artifact)
            interviewer_audio_id = reply_artifact.id

        interviewer_turn = Turn(
            id=self._ids.new_id(),
            session_id=session.id,
            index=turn_index * 2 + 1,
            kind=compose["kind"],
            question_ref=compose["question_ref"],
            transcript=str(compose["text"]),
            audio_artifact_id=interviewer_audio_id,
            usage=compose["usage"],
            created_at=self._clock.now(),
        )
        await self._turns.add(interviewer_turn)

        updated_session = Session(
            id=session.id,
            invite_id=session.invite_id,
            persona_id=session.persona_id,
            phase=compose["session_phase"],
            candidate_name=compose["session_candidate_name"],
            name_confidence=compose["session_name_confidence"],
            coverage={ref: QuestionCoverage(**c) for ref, c in compose["session_coverage"].items()},
            started_at=session.started_at,
            ended_at=session.ended_at,
        )
        await self._sessions.update(updated_session)

        return {
            "candidate_turn_id": candidate_turn.id,
            "interviewer_turn_id": interviewer_turn.id,
            "ends_session": compose["ends_session"],
        }


def _last_question_ref(turns: Sequence[Turn]) -> str | None:
    for turn in sorted(turns, key=lambda t: t.index, reverse=True):
        if turn.index % 2 == 1 and turn.question_ref is not None:
            return turn.question_ref
    return None


def build_turn_steps(
    *,
    storage: BlobStore,
    stt: SpeechToTextPort,
    tts: TextToSpeechPort,
    pipeline: TurnPipeline,
    personas: PersonaRepository,
    sessions: SessionRepository,
    turns: TurnRepository,
    artifacts: ArtifactRepository,
    clock: Clock,
    ids: IdGenerator,
) -> tuple[BaseStep, ...]:
    return (
        PersistAudioStep(storage=storage, artifacts=artifacts, clock=clock, ids=ids),
        TranscribeStep(stt=stt, storage=storage),
        ComposeStep(pipeline=pipeline, personas=personas, sessions=sessions, turns=turns),
        SynthesizeStep(tts=tts, storage=storage, ids=ids, clock=clock),
        CommitTurnStep(sessions=sessions, turns=turns, artifacts=artifacts, clock=clock, ids=ids),
    )
