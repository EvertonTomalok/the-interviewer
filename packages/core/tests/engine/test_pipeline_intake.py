from __future__ import annotations

import json

from interviewer_core.engine.pipeline import TurnPipeline
from interviewer_core.engine.types import HistoryTurn, TurnRequest


async def test_intake_extracts_name_and_asks_the_first_question(
    persona_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory()
    llm = fake_llm(
        [
            json.dumps({"name": "Ana Ribeiro"}),
            "Could you tell me about a slow query you've optimized?",
        ]
    )
    request = TurnRequest(
        persona=persona,
        session=session_factory(),
        history=(),
        candidate_text="hi, I'm Ana Ribeiro",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.session.candidate_name == "Ana Ribeiro"
    assert outcome.session.name_confidence == 1.0
    assert outcome.session.phase == "questioning"
    assert outcome.kind == "question"
    assert outcome.question_ref == "q1"
    assert outcome.text == "Could you tell me about a slow query you've optimized?"
    assert outcome.question_number == 1
    assert outcome.question_total == 1


async def test_no_name_found_re_asks_once(persona_factory, session_factory, fake_llm) -> None:
    persona = persona_factory()
    llm = fake_llm([json.dumps({"name": None})])
    request = TurnRequest(
        persona=persona, session=session_factory(), history=(), candidate_text="uh, hello there"
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.kind == "intake"
    assert outcome.text == persona.intake_prompt_text
    assert outcome.session.phase == "intake"
    assert outcome.session.candidate_name is None
    assert len(llm.calls) == 1


async def test_no_name_on_second_try_falls_back_to_the_transcript(
    persona_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory()
    llm = fake_llm(
        [
            json.dumps({"name": None}),
            "Could you tell me about a slow query you've optimized?",
        ]
    )
    history = (
        HistoryTurn(
            kind="intake",
            question_ref=None,
            asked_text=persona.greeting_text,
            candidate_text="huh?",
        ),
    )
    request = TurnRequest(
        persona=persona,
        session=session_factory(),
        history=history,
        candidate_text="still can't hear you",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.session.candidate_name == "still can't hear you"
    assert outcome.session.name_confidence == 0.0
    assert outcome.session.phase == "questioning"
    assert outcome.kind == "question"


async def test_the_first_question_is_the_pinned_versions_own(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    old = persona_factory(version=1, questions=(question_factory(ref="from_v1"),))
    persona_factory(version=2, questions=(question_factory(ref="from_v2"),))  # not passed to run()
    llm = fake_llm([json.dumps({"name": "Ana"}), "Question text, would that be fine?"])
    request = TurnRequest(
        persona=old, session=session_factory(), history=(), candidate_text="hi I'm Ana"
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.question_ref == "from_v1"
