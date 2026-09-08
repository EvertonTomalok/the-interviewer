from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from interviewer_core.engine.evaluator import evaluate
from interviewer_core.engine.types import HistoryTurn
from interviewer_core.errors import DomainError
from interviewer_core.ports.clock import FrozenClock
from interviewer_core.ports.ids import SeqIds


def _report_deps():
    return FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)), SeqIds("report")


def _two_question_persona(persona_factory, question_factory):
    return persona_factory(
        questions=(
            question_factory(ref="q1", expected_answer="added a database index"),
            question_factory(ref="q2", expected_answer="wrote a smaller test suite"),
        )
    )


def _scored(
    ref: str, score: float, verdict: str, rationale: str = "solid answer"
) -> dict[str, object]:
    return {"ref": ref, "score": score, "verdict": verdict, "rationale": rationale}


async def test_intake_and_closing_turns_are_excluded_from_the_evaluators_input(
    persona_factory, question_factory, fake_llm
) -> None:
    persona = _two_question_persona(persona_factory, question_factory)
    history = (
        HistoryTurn(
            kind="intake",
            question_ref=None,
            asked_text="Hi, what's your name?",
            candidate_text="Ana",
        ),
        HistoryTurn(
            kind="question", question_ref="q1", asked_text="q1", candidate_text="I added an index"
        ),
        HistoryTurn(
            kind="closing", question_ref=None, asked_text="Thanks, bye!", candidate_text=""
        ),
    )
    llm = fake_llm([json.dumps({"scores": [_scored("q1", 0.8, "strong")]})])
    clock, ids = _report_deps()

    report = await evaluate(
        session_id="s1", persona=persona, history=history, llm=llm, clock=clock, ids=ids
    )

    prompt_text = llm.calls[0][1].content
    assert "Ana" not in prompt_text
    assert "Thanks, bye" not in prompt_text
    by_ref = {s.question_ref: s for s in report.scores}
    assert by_ref["q2"].verdict == "not_answered"


async def test_an_answer_matching_expectation_scores_above_one_that_misses_it(
    persona_factory, question_factory, fake_llm
) -> None:
    persona = _two_question_persona(persona_factory, question_factory)
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
        HistoryTurn(kind="question", question_ref="q2", asked_text="q2", candidate_text="b"),
    )
    llm = fake_llm(
        [
            json.dumps(
                {
                    "scores": [
                        _scored("q1", 0.9, "strong"),
                        _scored("q2", 0.1, "weak", "answer misses the point entirely"),
                    ]
                }
            )
        ]
    )
    clock, ids = _report_deps()

    report = await evaluate(
        session_id="s1", persona=persona, history=history, llm=llm, clock=clock, ids=ids
    )

    by_ref = {s.question_ref: s for s in report.scores}
    assert by_ref["q1"].score > by_ref["q2"].score


async def test_a_question_never_asked_is_reported_answered_false_and_still_counted(
    persona_factory, question_factory, fake_llm
) -> None:
    persona = _two_question_persona(persona_factory, question_factory)
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
    )
    llm = fake_llm([json.dumps({"scores": [_scored("q1", 1.0, "strong")]})])
    clock, ids = _report_deps()

    report = await evaluate(
        session_id="s1", persona=persona, history=history, llm=llm, clock=clock, ids=ids
    )

    by_ref = {s.question_ref: s for s in report.scores}
    assert by_ref["q2"].verdict == "not_answered"
    assert by_ref["q2"].score == 0.0
    assert len(report.scores) == 2
    # unweighted mean of [1.0, 0.0] over two equal-weight questions
    assert report.overall_score == pytest.approx(0.5)


async def test_overall_score_respects_weight(persona_factory, question_factory, fake_llm) -> None:
    persona = persona_factory(
        questions=(
            question_factory(ref="q1", expected_answer="x", weight=3.0),
            question_factory(ref="q2", expected_answer="y", weight=1.0),
        )
    )
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
        HistoryTurn(kind="question", question_ref="q2", asked_text="q2", candidate_text="b"),
    )
    llm = fake_llm(
        [json.dumps({"scores": [_scored("q1", 1.0, "strong"), _scored("q2", 0.0, "weak")]})]
    )
    clock, ids = _report_deps()

    report = await evaluate(
        session_id="s1", persona=persona, history=history, llm=llm, clock=clock, ids=ids
    )

    # weight 3 on the perfect score pulls the mean well above the midpoint
    assert report.overall_score == pytest.approx(0.75)


async def test_overall_score_is_zero_when_every_question_has_zero_weight(
    persona_factory, question_factory, fake_llm
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1", expected_answer="x", weight=0.0),)
    )
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
    )
    llm = fake_llm([json.dumps({"scores": [_scored("q1", 0.9, "strong")]})])
    clock, ids = _report_deps()

    report = await evaluate(
        session_id="s1", persona=persona, history=history, llm=llm, clock=clock, ids=ids
    )

    assert report.overall_score == 0.0


async def test_unknown_ref_missing_rationale_or_bad_verdict_raise_domain_error(
    persona_factory, question_factory, fake_llm
) -> None:
    persona = _two_question_persona(persona_factory, question_factory)
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
    )
    clock, ids = _report_deps()

    bad_ref = fake_llm([json.dumps({"scores": [_scored("nonexistent", 0.5, "strong")]})])
    with pytest.raises(DomainError, match="unknown question ref"):
        await evaluate(
            session_id="s1", persona=persona, history=history, llm=bad_ref, clock=clock, ids=ids
        )

    missing_rationale = fake_llm(
        [
            json.dumps(
                {"scores": [{"ref": "q1", "score": 0.5, "verdict": "strong", "rationale": ""}]}
            )
        ]
    )
    with pytest.raises(DomainError, match="missing a rationale"):
        await evaluate(
            session_id="s1",
            persona=persona,
            history=history,
            llm=missing_rationale,
            clock=clock,
            ids=ids,
        )

    bad_verdict = fake_llm([json.dumps({"scores": [_scored("q1", 0.5, "amazing")]})])
    with pytest.raises(DomainError, match="verdict"):
        await evaluate(
            session_id="s1", persona=persona, history=history, llm=bad_verdict, clock=clock, ids=ids
        )


async def test_the_report_records_the_pinned_persona_and_a_newer_version_does_not_change_it(
    persona_factory, question_factory, fake_llm
) -> None:
    old = persona_factory(
        id="persona-v1", version=1, questions=(question_factory(ref="q1", expected_answer="x"),)
    )
    new = persona_factory(
        id="persona-v2", version=2, questions=(question_factory(ref="q1", expected_answer="x"),)
    )
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
    )
    clock, ids = _report_deps()

    old_llm = fake_llm([json.dumps({"scores": [_scored("q1", 0.9, "strong")]})])
    old_report = await evaluate(
        session_id="s1", persona=old, history=history, llm=old_llm, clock=clock, ids=ids
    )

    new_llm = fake_llm([json.dumps({"scores": [_scored("q1", 0.1, "weak")]})])
    await evaluate(session_id="s1", persona=new, history=history, llm=new_llm, clock=clock, ids=ids)

    assert old_report.persona_id == "persona-v1"
    assert old_report.overall_score == pytest.approx(
        0.9
    )  # unaffected by the later call against `new`
