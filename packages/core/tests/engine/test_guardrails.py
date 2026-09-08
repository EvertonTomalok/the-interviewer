from __future__ import annotations

from interviewer_core.engine.guardrails import amendment_for, check_question
from interviewer_core.engine.types import HistoryTurn


def test_a_clean_question_passes_every_check(persona_factory, question_factory) -> None:
    persona = persona_factory(language="en", max_tokens=800)
    question = question_factory(expected_answer="added a database index")
    assert check_question("What did you do to speed up the query?", question, persona, ()) == ()


def test_empty_text_fails(persona_factory, question_factory) -> None:
    persona = persona_factory()
    question = question_factory()
    assert "empty" in check_question("", question, persona, ())


def test_text_without_a_question_mark_fails(persona_factory, question_factory) -> None:
    persona = persona_factory()
    question = question_factory()
    failures = check_question("Tell me about the query.", question, persona, ())
    assert "not_a_question" in failures


def test_near_duplicate_of_an_already_asked_question_fails(
    persona_factory, question_factory
) -> None:
    persona = persona_factory()
    question = question_factory()
    history = (
        HistoryTurn(
            kind="question",
            question_ref="q0",
            asked_text="Can you tell me about a slow query you optimized?",
            candidate_text="sure",
        ),
    )
    failures = check_question(
        "Could you tell me about a slow query you optimized?", question, persona, history
    )
    assert "near_duplicate" in failures


def test_a_differently_worded_question_is_not_flagged_as_duplicate(
    persona_factory, question_factory
) -> None:
    persona = persona_factory()
    question = question_factory()
    history = (
        HistoryTurn(
            kind="question",
            question_ref="q0",
            asked_text="What's your favorite database?",
            candidate_text="x",
        ),
    )
    failures = check_question("How do you approach code review?", question, persona, history)
    assert "near_duplicate" not in failures


def test_leaking_the_expected_answer_fails(persona_factory, question_factory) -> None:
    persona = persona_factory()
    question = question_factory(expected_answer="mentions adding a database index")
    text = "Did you fix it by mentions adding a database index or something else?"
    assert "leaks_expected_answer" in check_question(text, question, persona, ())


def test_a_short_expected_answer_is_never_checked_for_leaking(
    persona_factory, question_factory
) -> None:
    persona = persona_factory()
    question = question_factory(expected_answer="yes")  # shorter than _MIN_LEAK_LENGTH
    assert "leaks_expected_answer" not in check_question("Did you say yes?", question, persona, ())


def test_a_portuguese_persona_is_never_flagged_wrong_language(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(language="pt-BR")
    question = question_factory()
    assert "wrong_language" not in check_question("O que voce fez a seguir?", question, persona, ())


def test_too_long_fails_when_it_exceeds_the_word_budget(persona_factory, question_factory) -> None:
    persona = persona_factory(max_tokens=3)
    question = question_factory()
    assert "too_long" in check_question("one two three four five?", question, persona, ())


def test_wrong_language_flags_portuguese_markers_in_an_english_persona(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(language="en")
    question = question_factory()
    assert "wrong_language" in check_question(
        "Você poderia me contar sobre isso?", question, persona, ()
    )


def test_amendment_for_joins_one_line_per_failure() -> None:
    text = amendment_for(["not_a_question", "too_long"])
    assert "phrased as a question" in text
    assert "ran too long" in text


def test_amendment_for_empty_failures_is_empty() -> None:
    assert amendment_for(()) == ""
