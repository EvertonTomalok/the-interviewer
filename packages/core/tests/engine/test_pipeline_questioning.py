from __future__ import annotations

from interviewer_core.domain.entities import QuestionCoverage
from interviewer_core.engine.pipeline import TurnPipeline
from interviewer_core.engine.types import HistoryTurn, TurnRequest


def _three_question_persona(persona_factory, question_factory, **overrides):
    questions = (
        question_factory(ref="q1", expected_answer="added a database index"),
        question_factory(ref="q2", expected_answer="wrote a smaller test suite first"),
        question_factory(ref="q3", expected_answer="paired with a senior engineer"),
    )
    base: dict[str, object] = {
        "questions": questions,
        "policy": "guided",
        "min_coverage": 0.9,
        "max_questions": 8,
    }
    base.update(overrides)
    return persona_factory(**base)


async def test_an_answer_covering_q2_marks_it_and_the_next_question_targets_a_different_ref(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = _three_question_persona(persona_factory, question_factory)
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=1.0),
        "q2": QuestionCoverage(asked=True, answered=False, confidence=0.0),
    }
    history = (
        HistoryTurn(
            kind="question", question_ref="q1", asked_text="q1 asked", candidate_text="index"
        ),
        HistoryTurn(kind="question", question_ref="q2", asked_text="q2 asked", candidate_text=""),
    )
    llm = fake_llm(["What did pairing with a senior engineer teach you?"])
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="I wrote a smaller test suite first",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.session.coverage["q2"].answered is True
    assert outcome.kind == "question"
    assert outcome.question_ref == "q3"
    assert outcome.question_number == 3
    assert outcome.question_total == 3


async def test_max_questions_ends_the_session_with_that_reason(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = _three_question_persona(
        persona_factory, question_factory, min_coverage=0.99, max_questions=1
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=False, confidence=0.0)}
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 asked", candidate_text=""),
    )
    llm = fake_llm([])
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="index",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.end_reason == "max_questions"
    assert outcome.ends_session is True
    assert outcome.kind == "closing"


async def test_min_coverage_reached_on_every_question_ends_the_session_with_that_reason(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1", expected_answer="added a database index"),),
        min_coverage=0.5,
        max_questions=8,
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=False, confidence=0.0)}
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 asked", candidate_text=""),
    )
    llm = fake_llm([])
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="I added a database index",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.end_reason == "min_coverage"


async def test_closing_ships_the_farewell_text_verbatim_with_no_model_call(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1", expected_answer="added a database index"),),
        min_coverage=0.5,
        max_questions=8,
        farewell_text="That's everything -- thanks for your time!",
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=False, confidence=0.0)}
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 asked", candidate_text=""),
    )
    llm = fake_llm([])  # no scripted answers: proves nothing gets asked of it
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="I added a database index",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.text == persona.farewell_text
    assert outcome.session.phase == "closing"
    assert len(llm.calls) == 0


async def test_a_duplicate_question_regenerates_once_then_falls_back_scripted_and_degraded(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory(
        questions=(
            question_factory(ref="q1", expected_answer="added a database index"),
            question_factory(
                ref="q2", text="Tell me about your testing habits.", expected_answer="tests first"
            ),
        ),
        policy="guided",
        min_coverage=0.99,
        max_questions=8,
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=1.0)}
    history = (
        HistoryTurn(
            kind="question", question_ref="q1", asked_text="q1 asked", candidate_text="index"
        ),
    )
    # Neither scripted reply is phrased as a question -- both fail the guard.
    llm = fake_llm(["This is a flat statement.", "Still not a question either."])
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="I added an index",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.degraded is True
    assert outcome.text == "Tell me about your testing habits."
    assert len(llm.calls) == 2


async def test_a_bad_first_draft_is_replaced_by_a_clean_regeneration_not_degraded(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory(
        questions=(
            question_factory(ref="q1", expected_answer="added a database index"),
            question_factory(ref="q2", expected_answer="tests first"),
        ),
        policy="guided",
        min_coverage=0.99,
        max_questions=8,
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=1.0)}
    history = (
        HistoryTurn(
            kind="question", question_ref="q1", asked_text="q1 asked", candidate_text="index"
        ),
    )
    llm = fake_llm(["A flat statement, not a question.", "How do you approach testing?"])
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="whatever",
    )

    outcome = await TurnPipeline(llm).run(request)

    assert outcome.degraded is False
    assert outcome.text == "How do you approach testing?"
    assert len(llm.calls) == 2


async def test_expected_answer_never_reaches_the_interview_prompt(
    persona_factory, question_factory, session_factory, fake_llm
) -> None:
    persona = persona_factory(
        questions=(
            question_factory(ref="q1", expected_answer="a very specific secret phrase"),
            question_factory(ref="q2", expected_answer="another secret phrase"),
        ),
        policy="guided",
        min_coverage=0.99,
        max_questions=8,
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=1.0)}
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 asked", candidate_text="x"),
    )
    llm = fake_llm(["A clean follow-up question?"])
    request = TurnRequest(
        persona=persona,
        session=session_factory(phase="questioning", coverage=coverage),
        history=history,
        candidate_text="whatever",
    )

    await TurnPipeline(llm).run(request)

    for call in llm.calls:
        for message in call:
            assert "secret phrase" not in message.content
