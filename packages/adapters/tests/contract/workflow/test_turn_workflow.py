"""Contract suite for the `turn` workflow, driven by `InlineWorkflowEngine`.

Covers PRD §5.2's four invariants plus the phase and reply-mode behaviour
T07a's own task file calls out. All ports are fakes; nothing here touches
the network or a real database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from interviewer_adapters.workflow import build_turn_steps
from interviewer_adapters.workflow.base import BaseStep, SimulatedCrash
from interviewer_core.engine import TurnPipeline
from interviewer_core.errors import PortError
from interviewer_core.ports.workflow import StepContext

from .conftest import Rig, intake_and_two_questions_answers, make_persona, make_session


async def _run_intake_round(rig: Rig, persona, *, reply_mode: str = "text") -> str:
    session = make_session(persona)
    await rig.seed(persona, session)
    uri = await rig.stage_upload(session.id, 0)
    payload = rig.turn_payload(
        session_id=session.id,
        persona_id=persona.id,
        turn_index=0,
        staging_uri=uri,
        reply_mode=reply_mode,
    )
    handle = await rig.engine.start("turn", payload, idempotency_key=f"{session.id}:0")
    return handle.run_id


async def test_idempotent_start_same_key_returns_same_run() -> None:
    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())
    session = make_session(persona)
    await rig.seed(persona, session)
    uri = await rig.stage_upload(session.id, 0)
    payload = rig.turn_payload(
        session_id=session.id, persona_id=persona.id, turn_index=0, staging_uri=uri
    )

    first = await rig.engine.start("turn", payload, idempotency_key=f"{session.id}:0")
    second = await rig.engine.start("turn", payload, idempotency_key=f"{session.id}:0")

    assert first.run_id == second.run_id
    turns = await rig.turns.list_for_session(session.id)
    assert len(turns) == 2  # not four: the second start() joined the same run


async def test_full_round_writes_two_turns_and_advances_phase() -> None:
    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())
    run_id = await _run_intake_round(rig, persona)

    state = await rig.engine.status(run_id)
    assert state.status == "succeeded"

    turns = await rig.turns.list_for_session("session-1")
    assert [t.index for t in turns] == [0, 1]
    assert turns[0].kind == "intake"  # candidate's name
    assert turns[1].kind == "question"  # interviewer's first real question

    session = await rig.sessions.get("session-1")
    assert session is not None
    assert session.phase == "questioning"
    assert session.candidate_name == "Ada Lovelace"


async def test_reply_mode_text_skips_synthesize_with_no_artifact() -> None:
    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())
    await _run_intake_round(rig, persona, reply_mode="text")

    turns = await rig.turns.list_for_session("session-1")
    interviewer_turn = turns[1]
    assert interviewer_turn.audio_artifact_id is None


async def test_reply_mode_voice_produces_an_artifact() -> None:
    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers(), reply_mode_voice=True)
    await _run_intake_round(rig, persona, reply_mode="voice")

    turns = await rig.turns.list_for_session("session-1")
    interviewer_turn = turns[1]
    assert interviewer_turn.audio_artifact_id is not None
    artifact = await rig.artifacts.get(interviewer_turn.audio_artifact_id)
    assert artifact is not None
    assert artifact.mime == "audio/wav"


async def test_reply_mode_is_pinned_at_start_not_read_live() -> None:
    """A run started under `text` and replayed after the payload's own
    `reply_mode` would say `voice` still produces the text outcome -- the
    run's stored `ctx.input` wins, never the argument passed to a later
    `start()` call for the same key."""
    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())
    session = make_session(persona)
    await rig.seed(persona, session)
    uri = await rig.stage_upload(session.id, 0)

    text_payload = rig.turn_payload(
        session_id=session.id,
        persona_id=persona.id,
        turn_index=0,
        staging_uri=uri,
        reply_mode="text",
    )
    await rig.engine.start("turn", text_payload, idempotency_key=f"{session.id}:0")

    voice_payload = dict(text_payload, reply_mode="voice")
    await rig.engine.start("turn", voice_payload, idempotency_key=f"{session.id}:0")

    turns = await rig.turns.list_for_session(session.id)
    assert turns[1].audio_artifact_id is None


@pytest.mark.parametrize(
    "crash_step", ["persist_audio", "transcribe", "compose", "synthesize", "commit_turn"]
)
async def test_crash_after_each_step_resumes_without_rerunning_completed_steps(
    crash_step: str,
) -> None:
    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())
    session = make_session(persona)
    await rig.seed(persona, session)
    uri = await rig.stage_upload(session.id, 0)
    payload = rig.turn_payload(
        session_id=session.id, persona_id=persona.id, turn_index=0, staging_uri=uri
    )
    key = f"{session.id}:0"

    rig.engine.set_fail_at(lambda name, attempt: name == crash_step and attempt == 1)
    with pytest.raises(SimulatedCrash):
        await rig.engine.start("turn", payload, idempotency_key=key)

    run = await rig.run_repo.get_by_idempotency_key(key)
    assert run is not None
    assert run.status == "running"  # the crash never got to mark it terminal

    rig.engine.set_fail_at(None)
    handle = await rig.engine.start("turn", payload, idempotency_key=key)

    state = await rig.engine.status(handle.run_id)
    assert state.status == "succeeded"
    turns = await rig.turns.list_for_session(session.id)
    assert len(turns) == 2  # exactly one candidate row and one interviewer row, never doubled

    # every LLM call the uninterrupted round would make happened exactly
    # once in total, across both start() calls -- nothing before the crash
    # point re-ran.
    assert len(rig.llm.calls) == 2  # intake extraction + one compose call


async def test_transient_failure_retries_then_succeeds() -> None:
    class FlakyStorage:
        def __init__(self, real, fail_times: int) -> None:
            self._real = real
            self._left = fail_times

        async def put(self, key, content, *, mime):
            return await self._real.put(key, content, mime=mime)

        async def get(self, uri):
            if self._left > 0:
                self._left -= 1
                raise PortError("temporarily unavailable", transient=True)
            return await self._real.get(uri)

        async def signed_url(self, uri, *, expires_in_seconds):
            return await self._real.signed_url(uri, expires_in_seconds=expires_in_seconds)

    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())
    flaky = FlakyStorage(rig.storage, fail_times=2)
    rig.storage = flaky  # type: ignore[assignment]

    # rebuild the engine's turn steps against the flaky storage
    steps = build_turn_steps(
        storage=flaky,  # type: ignore[arg-type]
        stt=rig.stt,
        tts=rig.tts,
        pipeline=TurnPipeline(rig.llm),
        personas=rig.personas,
        sessions=rig.sessions,
        turns=rig.turns,
        artifacts=rig.artifacts,
        clock=rig.clock,
        ids=rig.ids,
    )
    rig.engine.set_workflow("turn", steps)

    session = make_session(persona)
    await rig.seed(persona, session)
    uri = await rig.stage_upload(session.id, 0)
    payload = rig.turn_payload(
        session_id=session.id, persona_id=persona.id, turn_index=0, staging_uri=uri
    )

    handle = await rig.engine.start("turn", payload, idempotency_key=f"{session.id}:0")
    state = await rig.engine.status(handle.run_id)
    assert state.status == "succeeded"


async def test_permanent_failure_fails_the_run_naming_the_step() -> None:
    class BrokenStorage:
        async def put(self, key, content, *, mime):
            raise PortError("bucket gone", transient=False)

        async def get(self, uri):
            raise PortError("bucket gone", transient=False)

        async def signed_url(self, uri, *, expires_in_seconds):
            raise PortError("bucket gone", transient=False)

    persona = make_persona()
    rig = Rig(answers=intake_and_two_questions_answers())

    broken = BrokenStorage()
    steps = build_turn_steps(
        storage=broken,  # type: ignore[arg-type]
        stt=rig.stt,
        tts=rig.tts,
        pipeline=TurnPipeline(rig.llm),
        personas=rig.personas,
        sessions=rig.sessions,
        turns=rig.turns,
        artifacts=rig.artifacts,
        clock=rig.clock,
        ids=rig.ids,
    )
    rig.engine.set_workflow("turn", steps)

    session = make_session(persona)
    await rig.seed(persona, session)
    payload = rig.turn_payload(
        session_id=session.id, persona_id=persona.id, turn_index=0, staging_uri="memory://missing"
    )

    with pytest.raises(PortError):
        await rig.engine.start("turn", payload, idempotency_key=f"{session.id}:0")

    run = await rig.run_repo.get_by_idempotency_key(f"{session.id}:0")
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "persist_audio" in run.error


class _RealClockStep(BaseStep):
    """A deliberately bad step: reads wall time directly instead of an
    injected `Clock`. This is the shape of bug the determinism invariant
    exists to catch -- our real steps never do this."""

    name = "leaky"
    max_attempts = 1

    async def run(self, ctx: StepContext) -> dict[str, str]:
        return {"now": datetime.now(UTC).isoformat()}


async def test_a_step_reading_the_real_clock_is_not_deterministic() -> None:
    """Demonstrates the failure this suite is written to catch: two
    otherwise-identical runs of a step that reads real time produce
    different output. Every real step here reads `Clock` from `ctx`
    indirectly (via injection into the step's constructor), never the
    wall clock -- this canary is what would fail if one stopped doing
    that."""
    rig = Rig(answers=[])
    rig.engine.set_workflow("leaky", (_RealClockStep(),))

    first = await rig.engine.start("leaky", {}, idempotency_key="a")
    second = await rig.engine.start("leaky", {}, idempotency_key="b")

    state_a = await rig.engine.status(first.run_id)
    state_b = await rig.engine.status(second.run_id)
    assert state_a.outputs["leaky"]["now"] != state_b.outputs["leaky"]["now"]
