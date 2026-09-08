"""Coverage bookkeeping: what each persona question has reached so far.

`asked`/`follow-up` counts are never stored as their own field -- they are
read back off `history`, the same way `question_number` is, so a reloaded
page (or a retried call with the same history) recomputes the identical
number instead of drifting from a counter nobody persisted.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from interviewer_core.domain.entities import Persona, PersonaQuestion, QuestionCoverage
from interviewer_core.engine.types import EndReason, HistoryTurn

_WORD = re.compile(r"[a-z0-9]+")


def times_asked(ref: str, history: Sequence[HistoryTurn]) -> int:
    """How many turns (first ask plus every follow-up) targeted `ref`."""
    counts = Counter(h.question_ref for h in history if h.kind == "question")
    return counts[ref]


def assess_answer(question: PersonaQuestion, candidate_text: str) -> tuple[bool, float]:
    """`(answered, confidence)` from how much of `expected_answer`'s vocabulary
    the candidate's own words cover.

    Deterministic and in-code -- like every other rule in this package --
    so a completion check never depends on a model call that could itself
    fail; the closing turn spends nothing (see `pipeline.py`).
    """
    if not candidate_text.strip():
        return False, 0.0
    expected_words = set(_WORD.findall(question.expected_answer.lower()))
    if not expected_words:
        return True, 1.0
    candidate_words = set(_WORD.findall(candidate_text.lower()))
    confidence = len(candidate_words & expected_words) / len(expected_words)
    return confidence > 0.0, min(1.0, confidence)


def mark_asked(
    coverage: Mapping[str, QuestionCoverage], ref: str
) -> Mapping[str, QuestionCoverage]:
    """Return coverage with `ref` flagged `asked`, leaving everything else untouched."""
    current = coverage.get(ref, QuestionCoverage())
    if current.asked:
        return coverage
    updated = dict(coverage)
    updated[ref] = QuestionCoverage(
        asked=True, answered=current.answered, confidence=current.confidence
    )
    return updated


def mark_answered(
    coverage: Mapping[str, QuestionCoverage], ref: str, *, answered: bool, confidence: float
) -> Mapping[str, QuestionCoverage]:
    """Return coverage with `ref`'s answer recorded. Answering implies asked."""
    updated = dict(coverage)
    updated[ref] = QuestionCoverage(asked=True, answered=answered, confidence=confidence)
    return updated


def completion_reason(
    persona: Persona, coverage: Mapping[str, QuestionCoverage]
) -> EndReason | None:
    """`None` while the session should keep asking; otherwise why it stops.

    Checked in this order because the two can fire on the same turn -- the
    last answer that finally clears every question's floor is also, often,
    the `max_questions`-th one -- and the honest reason is that coverage
    closed it, not that the budget ran out under it.
    """
    if all(
        coverage.get(q.ref, QuestionCoverage()).confidence >= persona.min_coverage
        for q in persona.questions
    ):
        return "min_coverage"
    asked_so_far = sum(1 for cov in coverage.values() if cov.asked)
    if asked_so_far >= persona.max_questions:
        return "max_questions"
    return None


def question_numbers(persona: Persona, coverage: Mapping[str, QuestionCoverage]) -> tuple[int, int]:
    """`(question_number, question_total)` -- always derived, never counted client-side."""
    asked_so_far = sum(1 for cov in coverage.values() if cov.asked)
    return asked_so_far, len(persona.questions)
