from __future__ import annotations

from interviewer_core.domain.entities import QuestionCoverage
from interviewer_core.engine.coverage import (
    assess_answer,
    completion_reason,
    mark_answered,
    mark_asked,
    question_numbers,
    times_asked,
)
from interviewer_core.engine.types import HistoryTurn


def test_assess_answer_scores_by_vocabulary_overlap_with_expected_answer(question_factory) -> None:
    question = question_factory(expected_answer="added a database index and rewrote the query")

    answered, confidence = assess_answer(question, "I added an index on the column")
    assert answered is True
    assert confidence > 0.0

    not_answered, zero_confidence = assess_answer(question, "")
    assert not_answered is False
    assert zero_confidence == 0.0

    unrelated, low_confidence = assess_answer(question, "I like turtles")
    assert unrelated is False
    assert low_confidence == 0.0


def test_assess_answer_with_no_scoreable_words_in_the_expected_answer_trusts_any_reply(
    question_factory,
) -> None:
    question = question_factory(expected_answer="!!!")  # non-empty, but no [a-z0-9] tokens
    answered, confidence = assess_answer(question, "anything at all")
    assert (answered, confidence) == (True, 1.0)


def test_mark_asked_is_idempotent_and_preserves_existing_answer() -> None:
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=0.8)}
    updated = mark_asked(coverage, "q1")
    assert updated == coverage

    fresh = mark_asked({}, "q2")
    assert fresh["q2"] == QuestionCoverage(asked=True, answered=False, confidence=0.0)


def test_mark_answered_implies_asked() -> None:
    updated = mark_answered({}, "q1", answered=True, confidence=0.9)
    assert updated["q1"] == QuestionCoverage(asked=True, answered=True, confidence=0.9)


def test_completion_reason_is_none_while_below_both_floors(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1"), question_factory(ref="q2")),
        min_coverage=0.7,
        max_questions=8,
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=0.9)}
    assert completion_reason(persona, coverage) is None


def test_completion_reason_min_coverage_when_every_question_clears_the_floor(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1"), question_factory(ref="q2")), min_coverage=0.7
    )
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=0.9),
        "q2": QuestionCoverage(asked=True, answered=True, confidence=0.8),
    }
    assert completion_reason(persona, coverage) == "min_coverage"


def test_completion_reason_max_questions_when_the_budget_is_spent(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1"), question_factory(ref="q2")),
        min_coverage=0.99,
        max_questions=1,
    )
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=0.1)}
    assert completion_reason(persona, coverage) == "max_questions"


def test_question_numbers_come_from_coverage_not_a_counter(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(
        questions=(
            question_factory(ref="q1"),
            question_factory(ref="q2"),
            question_factory(ref="q3"),
        )
    )
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=0.5),
        "q2": QuestionCoverage(asked=True, answered=False, confidence=0.0),
    }
    assert question_numbers(persona, coverage) == (2, 3)


def test_times_asked_counts_follow_ups_too() -> None:
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="a", candidate_text="x"),
        HistoryTurn(kind="question", question_ref="q1", asked_text="b", candidate_text="y"),
        HistoryTurn(kind="question", question_ref="q2", asked_text="c", candidate_text="z"),
    )
    assert times_asked("q1", history) == 2
    assert times_asked("q2", history) == 1
    assert times_asked("q3", history) == 0
