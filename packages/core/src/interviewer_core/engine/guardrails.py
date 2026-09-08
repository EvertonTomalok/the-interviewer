"""What ships before a question does. All deterministic, in code -- these
are the last read before the candidate hears it, not one more model call
that could itself go wrong.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence

from interviewer_core.domain.entities import Persona, PersonaQuestion
from interviewer_core.engine.types import HistoryTurn

#: Above this ratio (`difflib.SequenceMatcher`, on normalised text) a question
#: reads as the same one already asked, not a fresh rewrite of it.
_DUPLICATE_RATIO = 0.82

#: A leaked `expected_answer` shorter than this is too common a substring
#: (e.g. "yes") to trust a containment check on -- it would flag questions
#: that never came near the answer.
_MIN_LEAK_LENGTH = 8


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_question(text: str) -> bool:
    return "?" in text


def _near_duplicate(text: str, history: Sequence[HistoryTurn]) -> bool:
    candidate = _normalized(text)
    for turn in history:
        if turn.kind != "question" or not turn.asked_text:
            continue
        ratio = difflib.SequenceMatcher(None, candidate, _normalized(turn.asked_text)).ratio()
        if ratio >= _DUPLICATE_RATIO:
            return True
    return False


#: Cheap, honest heuristic -- stdlib carries no language identifier, and the
#: architecture test forbids importing one. Only Portuguese is distinguished
#: from everything else, which is all this product needs at PoC scope.
_PT_MARKERS = frozenset("áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ")


def _stays_in_language(text: str, persona: Persona) -> bool:
    is_pt = persona.language.lower().startswith("pt")
    has_pt_markers = any(ch in _PT_MARKERS for ch in text)
    if is_pt:
        return True  # a short question may legitimately carry no accented word
    return not has_pt_markers


def _within_length(text: str, persona: Persona) -> bool:
    # Persona carries no dedicated question-length field; `max_tokens` -- the
    # ceiling already set for this persona's LLM output -- doubles as the
    # word budget rather than inventing a second, unconfigurable one.
    return len(text.split()) <= persona.max_tokens


def _leaks_expected_answer(text: str, question: PersonaQuestion) -> bool:
    expected = question.expected_answer.strip()
    if len(expected) < _MIN_LEAK_LENGTH:
        return False
    return expected.casefold() in text.casefold()


def check_question(
    text: str,
    question: PersonaQuestion,
    persona: Persona,
    history: Sequence[HistoryTurn],
) -> tuple[str, ...]:
    """Every rule `text` fails, or `()` when it is clear to ship."""
    failures = []
    if not text.strip():
        failures.append("empty")
    elif not _is_question(text):
        failures.append("not_a_question")
    if _near_duplicate(text, history):
        failures.append("near_duplicate")
    if not _stays_in_language(text, persona):
        failures.append("wrong_language")
    if not _within_length(text, persona):
        failures.append("too_long")
    if _leaks_expected_answer(text, question):
        failures.append("leaks_expected_answer")
    return tuple(failures)


_AMENDMENTS: dict[str, str] = {
    "empty": "Your last reply was empty. Ask the question in words this time.",
    "not_a_question": "Your last reply was not phrased as a question. Ask it as one.",
    "near_duplicate": "Your last reply repeated a question already asked. Word it differently.",
    "wrong_language": "Your last reply drifted out of the candidate's language. Stay in it.",
    "too_long": "Your last reply ran too long. Ask it in one short sentence.",
    "leaks_expected_answer": (
        "Your last reply gave away the expected answer. Ask the question without it."
    ),
}


def amendment_for(failures: Sequence[str]) -> str:
    return " ".join(_AMENDMENTS[code] for code in failures if code in _AMENDMENTS)
