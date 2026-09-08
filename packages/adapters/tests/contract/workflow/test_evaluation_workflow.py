"""Contract suite for the `evaluation` workflow: `collect_answers -> score
-> commit_report`. Same engine, same template, same guarantees as `turn` --
this is the second workflow that proves the engine is not special-cased for
either one."""

from __future__ import annotations

import json

import pytest

from interviewer_adapters.workflow.base import SimulatedCrash
from interviewer_core.domain.phase import advance
from interviewer_core.ports.llm import LLMAnswer, LLMUsage

from .conftest import Rig, make_persona, make_session

_ZERO = LLMUsage(prompt_tokens=0, completion_tokens=0)


def _scored_answer() -> LLMAnswer:
    payload = {
        "scores": [
            {"ref": "q1", "verdict": "strong", "score": 0.9, "rationale": "clear and complete"},
            {"ref": "q2", "verdict": "adequate", "score": 0.6, "rationale": "mostly there"},
        ]
    }
    return LLMAnswer(text=json.dumps(payload), usage=_ZERO)


async def _run_full_interview_to_closing(rig: Rig, persona) -> str:
    """Drives the `turn` workflow through intake and both questions, via
    the same engine, until the session reaches `closing`. Returns the
    session id."""
    session = make_session(persona)
    await rig.seed(persona, session)

    for turn_index in range(3):
        uri = await rig.stage_upload(session.id, turn_index)
        payload = rig.turn_payload(
            session_id=session.id, persona_id=persona.id, turn_index=turn_index, staging_uri=uri
        )
        await rig.engine.start("turn", payload, idempotency_key=f"{session.id}:{turn_index}")

    return session.id


def _eval_answers() -> list[LLMAnswer]:
    zero = _ZERO
    return [
        LLMAnswer(text='{"name": "Ada Lovelace"}', usage=zero),
        LLMAnswer(text="What is the first thing you want to tell me?", usage=zero),
        LLMAnswer(text="What is the second thing on your mind?", usage=zero),
        _scored_answer(),
    ]


async def test_evaluation_workflow_produces_a_report_and_completes_the_session() -> None:
    persona = make_persona()
    rig = Rig(answers=_eval_answers())
    session_id = await _run_full_interview_to_closing(rig, persona)

    closing = await rig.sessions.get(session_id)
    assert closing is not None
    assert closing.phase == "closing"
    await rig.sessions.update(advance(closing, "start_evaluation"))

    payload = {"session_id": session_id, "persona_id": persona.id}
    handle = await rig.engine.start("evaluation", payload, idempotency_key=f"{session_id}:report")
    state = await rig.engine.status(handle.run_id)
    assert state.status == "succeeded"

    report = await rig.reports.get_for_session(session_id)
    assert report is not None
    assert {s.question_ref for s in report.scores} == {"q1", "q2"}
    assert report.overall_score == pytest.approx(0.75)  # equal weights: mean of 0.9 and 0.6

    completed = await rig.sessions.get(session_id)
    assert completed is not None
    assert completed.phase == "completed"
    assert completed.ended_at is not None


async def test_evaluation_replay_does_not_call_the_model_again() -> None:
    persona = make_persona()
    rig = Rig(answers=_eval_answers())
    session_id = await _run_full_interview_to_closing(rig, persona)

    closing = await rig.sessions.get(session_id)
    assert closing is not None
    await rig.sessions.update(advance(closing, "start_evaluation"))

    payload = {"session_id": session_id, "persona_id": persona.id}
    key = f"{session_id}:report"
    await rig.engine.start("evaluation", payload, idempotency_key=key)
    calls_after_first = len(rig.llm.calls)

    handle = await rig.engine.start("evaluation", payload, idempotency_key=key)
    state = await rig.engine.status(handle.run_id)

    assert len(rig.llm.calls) == calls_after_first  # not one more
    assert state.status == "succeeded"
    report = await rig.reports.get_for_session(session_id)
    assert report is not None
    assert report.overall_score == pytest.approx(0.75)


async def test_evaluation_crash_after_score_resumes_without_rescoring() -> None:
    persona = make_persona()
    rig = Rig(answers=_eval_answers())
    session_id = await _run_full_interview_to_closing(rig, persona)

    closing = await rig.sessions.get(session_id)
    assert closing is not None
    await rig.sessions.update(advance(closing, "start_evaluation"))

    payload = {"session_id": session_id, "persona_id": persona.id}
    key = f"{session_id}:report"

    rig.engine.set_fail_at(lambda name, attempt: name == "commit_report" and attempt == 1)
    with pytest.raises(SimulatedCrash):
        await rig.engine.start("evaluation", payload, idempotency_key=key)
    calls_before_restart = len(rig.llm.calls)

    rig.engine.set_fail_at(None)
    handle = await rig.engine.start("evaluation", payload, idempotency_key=key)
    state = await rig.engine.status(handle.run_id)

    assert state.status == "succeeded"
    assert len(rig.llm.calls) == calls_before_restart  # score step did not re-run
    completed = await rig.sessions.get(session_id)
    assert completed is not None
    assert completed.phase == "completed"
