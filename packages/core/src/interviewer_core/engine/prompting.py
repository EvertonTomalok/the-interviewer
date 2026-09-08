"""Every prompt the engine sends, and the one thing they must never share:
`expected_answer` reaches only `build_evaluator_messages`. A model told the
answer while it is still asking the question asks it badly and often leaks
it -- see `packages/core/CONTEXT.md`, engine section, Traps.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from interviewer_core.domain.entities import Persona, PersonaQuestion
from interviewer_core.engine.types import HistoryTurn
from interviewer_core.ports.llm import LLMMessage

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Any | None:
    """The first `{...}` block in `text`, parsed -- or `None` on anything else.

    Models wrap JSON in prose or a fenced code block more often than not;
    this reads past both without asking for a second call.
    """
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        result: Any = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return result


def _already_asked(history: Sequence[HistoryTurn]) -> tuple[str, ...]:
    return tuple(h.asked_text for h in history if h.kind == "question" and h.asked_text)


def build_intake_messages(persona: Persona, candidate_text: str) -> tuple[LLMMessage, ...]:
    system = (
        f"You are the intake step of a {persona.language} voice interview. "
        "The candidate was asked their name. Read what they said and reply "
        'with only this JSON: {"name": string or null}. Use null when no '
        "name is present -- do not guess one."
    )
    return (
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=candidate_text),
    )


def build_assessment_messages(
    persona: Persona, question: PersonaQuestion, candidate_text: str
) -> tuple[LLMMessage, ...]:
    system = (
        f"You are grading whether a candidate's spoken answer engages with an "
        f"interview question, topic {question.topic!r}. Reply with only this "
        'JSON: {"answered": boolean, "confidence": number between 0 and 1}. '
        "`answered` is whether they attempted the question at all; "
        "`confidence` is how completely they covered it -- a partial or "
        "vague answer scores low, not zero."
    )
    user = f"Question: {question.text}\nCandidate said: {candidate_text}"
    return (
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    )


def build_question_messages(
    persona: Persona,
    question: PersonaQuestion,
    history: Sequence[HistoryTurn],
    *,
    amendment: str = "",
) -> tuple[LLMMessage, ...]:
    system = (
        f"You are conducting a {persona.language} voice interview in a "
        f"{persona.name} tone. Rewrite and, where natural, follow up on the "
        f"interviewer's question below -- do not invent a topic it does not "
        "list, and do not reveal or hint at what a correct answer looks "
        "like. Reply with only the question itself, in the candidate's "
        "language, no preamble."
    )
    already = _already_asked(history)
    lines = [f"Question to ask (topic: {question.topic}): {question.text}"]
    if already:
        lines.append(
            "Already asked, in this session -- do not repeat these: " + " | ".join(already)
        )
    if amendment:
        lines.append(amendment)
    return (
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content="\n".join(lines)),
    )


def build_evaluator_messages(
    persona: Persona, answers: Mapping[str, str]
) -> tuple[LLMMessage, ...]:
    system = (
        "You are scoring a finished interview transcript against a rubric. "
        "For every question below, judge the candidate's answer against its "
        "expected answer and the rubric, and reply with only this JSON: "
        '{"scores": [{"ref": string, "score": number 0-1, '
        '"verdict": "strong"|"adequate"|"weak"|"not_answered", '
        '"rationale": string}]}. One entry per question listed below, no '
        f"more, no fewer. Rubric: {persona.rubric}"
    )
    blocks = []
    for ref, transcript in answers.items():
        question = next(q for q in persona.questions if q.ref == ref)
        blocks.append(
            f"ref: {ref}\ntopic: {question.topic}\nquestion: {question.text}\n"
            f"expected answer: {question.expected_answer}\n"
            f"candidate said: {transcript}"
        )
    return (
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content="\n\n".join(blocks)),
    )
