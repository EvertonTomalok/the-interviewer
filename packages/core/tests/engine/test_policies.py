from __future__ import annotations

import pytest

from interviewer_core.domain.entities import QuestionCoverage
from interviewer_core.engine.policies import AdaptivePolicy, GuidedPolicy, StressPolicy, policy_for
from interviewer_core.engine.types import HistoryTurn
from interviewer_core.errors import ConfigError


def _three_questions(question_factory):
    return (
        question_factory(ref="q1", follow_up_depth=1),
        question_factory(ref="q2", follow_up_depth=1),
        question_factory(ref="q3", follow_up_depth=1),
    )


def test_guided_walks_questions_in_order_skipping_answered_ones(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(questions=_three_questions(question_factory), policy="guided")
    coverage = {"q1": QuestionCoverage(asked=True, answered=True, confidence=1.0)}

    assert GuidedPolicy().pick_next(persona, coverage, history=()) == "q2"


def test_adaptive_picks_the_weakest_covered_question(persona_factory, question_factory) -> None:
    persona = persona_factory(
        questions=_three_questions(question_factory), policy="adaptive", min_coverage=0.7
    )
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=0.9),
        "q2": QuestionCoverage(asked=True, answered=True, confidence=0.2),
        "q3": QuestionCoverage(asked=True, answered=True, confidence=0.5),
    }
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 text", candidate_text="a1"),
        HistoryTurn(kind="question", question_ref="q2", asked_text="q2 text", candidate_text="a2"),
        HistoryTurn(kind="question", question_ref="q3", asked_text="q3 text", candidate_text="a3"),
    )

    assert AdaptivePolicy().pick_next(persona, coverage, history) == "q2"


def test_adaptive_stops_following_up_past_follow_up_depth(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(
        questions=(
            question_factory(ref="q1", follow_up_depth=1),
            question_factory(ref="q2", follow_up_depth=1),
        ),
        policy="adaptive",
        min_coverage=0.7,
    )
    coverage = {
        "q1": QuestionCoverage(
            asked=True, answered=True, confidence=0.1
        ),  # weakest, but exhausted below
        "q2": QuestionCoverage(asked=True, answered=True, confidence=0.5),
    }
    # q1 already asked twice (1 initial + 1 follow-up == its follow_up_depth budget spent)
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 a", candidate_text="x"),
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1 b", candidate_text="y"),
    )

    assert AdaptivePolicy().pick_next(persona, coverage, history) == "q2"


def test_stress_pushes_on_the_most_confidently_answered_question(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(questions=_three_questions(question_factory), policy="stress")
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=0.4),
        "q2": QuestionCoverage(asked=True, answered=True, confidence=0.95),
        "q3": QuestionCoverage(asked=True, answered=True, confidence=0.6),
    }

    assert StressPolicy().pick_next(persona, coverage, history=()) == "q2"


def test_each_policy_given_identical_state_picks_a_different_question(
    persona_factory, question_factory
) -> None:
    questions = _three_questions(question_factory)
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=0.9),
        "q2": QuestionCoverage(asked=True, answered=True, confidence=0.2),
        "q3": QuestionCoverage(asked=True, answered=False, confidence=0.0),
    }
    history = (
        HistoryTurn(kind="question", question_ref="q1", asked_text="q1", candidate_text="a"),
        HistoryTurn(kind="question", question_ref="q2", asked_text="q2", candidate_text="b"),
        HistoryTurn(kind="question", question_ref="q3", asked_text="q3", candidate_text="c"),
    )
    persona = persona_factory(questions=questions, min_coverage=0.7)

    picks = {
        kind: policy_for(kind).pick_next(persona, coverage, history)
        for kind in ("guided", "adaptive", "stress")
    }

    assert picks == {"guided": "q3", "adaptive": "q3", "stress": "q1"}
    assert (
        len(set(picks.values())) == 2
    )  # guided and adaptive agree here; stress is the odd one out


def test_guided_falls_back_to_the_first_question_when_everything_is_answered(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(questions=_three_questions(question_factory))
    coverage = {
        ref: QuestionCoverage(asked=True, answered=True, confidence=1.0)
        for ref in ("q1", "q2", "q3")
    }

    assert GuidedPolicy().pick_next(persona, coverage, history=()) == "q1"


def test_adaptive_falls_back_to_the_weakest_when_everything_already_clears_the_floor(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(questions=_three_questions(question_factory), min_coverage=0.5)
    coverage = {
        "q1": QuestionCoverage(asked=True, answered=True, confidence=0.9),
        "q2": QuestionCoverage(asked=True, answered=True, confidence=0.6),
        "q3": QuestionCoverage(asked=True, answered=True, confidence=0.7),
    }

    # every question already clears `min_coverage`; the loop skips all three
    # (each hits `continue`) and falls back to the ranked-weakest one.
    assert AdaptivePolicy().pick_next(persona, coverage, history=()) == "q2"


def test_stress_falls_back_to_the_first_question_when_nothing_is_answered_yet(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(questions=_three_questions(question_factory))

    assert StressPolicy().pick_next(persona, coverage={}, history=()) == "q1"


def test_policy_for_unknown_kind_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="unknown question policy"):
        policy_for("nonexistent")  # type: ignore[arg-type]
