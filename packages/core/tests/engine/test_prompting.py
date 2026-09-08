from __future__ import annotations

from interviewer_core.engine.prompting import (
    build_evaluator_messages,
    build_intake_messages,
    build_question_messages,
    extract_json,
)
from interviewer_core.engine.types import HistoryTurn


def test_extract_json_reads_a_bare_object() -> None:
    assert extract_json('{"name": "Ana"}') == {"name": "Ana"}


def test_extract_json_reads_past_a_fenced_code_block() -> None:
    text = 'Sure, here it is:\n```json\n{"name": "Ana"}\n```\nHope that helps.'
    assert extract_json(text) == {"name": "Ana"}


def test_extract_json_returns_none_for_non_json_text() -> None:
    assert extract_json("Ana, no braces here") is None


def test_extract_json_returns_none_for_malformed_json() -> None:
    assert extract_json('{"name": "Ana", }') is None


def test_build_intake_messages_carries_the_candidate_text_verbatim(persona_factory) -> None:
    persona = persona_factory(language="en")
    messages = build_intake_messages(persona, "hi, I'm Ana Ribeiro")
    assert messages[1].content == "hi, I'm Ana Ribeiro"


def test_build_question_messages_lists_already_asked_questions(
    persona_factory, question_factory
) -> None:
    persona = persona_factory()
    question = question_factory(ref="q2")
    history = (
        HistoryTurn(
            kind="question", question_ref="q1", asked_text="What's your stack?", candidate_text="x"
        ),
    )
    messages = build_question_messages(persona, question, history)
    user_content = messages[1].content
    assert "What's your stack?" in user_content


def test_build_question_messages_never_mentions_expected_answer(
    persona_factory, question_factory
) -> None:
    persona = persona_factory()
    question = question_factory(expected_answer="a very specific secret phrase")
    messages = build_question_messages(persona, question, ())
    for message in messages:
        assert "secret phrase" not in message.content


def test_build_evaluator_messages_includes_expected_answer(
    persona_factory, question_factory
) -> None:
    persona = persona_factory(
        questions=(question_factory(ref="q1", expected_answer="a secret phrase"),)
    )
    messages = build_evaluator_messages(persona, {"q1": "the candidate's reply"})
    assert "a secret phrase" in messages[1].content
    assert "the candidate's reply" in messages[1].content
