"""`QuestionPolicy` as a Strategy, selected by a registry lookup -- never an
`if`/`elif` on `persona.policy`. Adding a fourth policy is a new class plus
one line in `_POLICIES`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from interviewer_core.domain.entities import Persona, QuestionCoverage, QuestionPolicyKind
from interviewer_core.engine.coverage import times_asked
from interviewer_core.engine.types import HistoryTurn
from interviewer_core.errors import ConfigError


class QuestionPolicy(Protocol):
    def pick_next(
        self,
        persona: Persona,
        coverage: Mapping[str, QuestionCoverage],
        history: Sequence[HistoryTurn],
    ) -> str:
        """Return the `ref` of the question to ask next (a fresh one, or a
        follow-up on one already asked)."""
        ...


class GuidedPolicy:
    """Walk the persona's questions in order, one each -- no follow-ups."""

    def pick_next(
        self,
        persona: Persona,
        coverage: Mapping[str, QuestionCoverage],
        history: Sequence[HistoryTurn],
    ) -> str:
        for q in persona.questions:
            if not coverage.get(q.ref, QuestionCoverage()).answered:
                return q.ref
        return persona.questions[0].ref


class AdaptivePolicy:
    """Weakest coverage first; follow up on it while it stays thin, up to
    that question's own `follow_up_depth`."""

    def pick_next(
        self,
        persona: Persona,
        coverage: Mapping[str, QuestionCoverage],
        history: Sequence[HistoryTurn],
    ) -> str:
        ranked = sorted(
            persona.questions,
            key=lambda q: coverage.get(q.ref, QuestionCoverage()).confidence,
        )
        for q in ranked:
            cov = coverage.get(q.ref, QuestionCoverage())
            if cov.confidence >= persona.min_coverage:
                continue
            asked = times_asked(q.ref, history)
            if asked == 0 or asked - 1 < q.follow_up_depth:
                return q.ref
        return ranked[0].ref


class StressPolicy:
    """Push again on whichever question the candidate answered most
    confidently -- the opposite reading of "weakest coverage"."""

    def pick_next(
        self,
        persona: Persona,
        coverage: Mapping[str, QuestionCoverage],
        history: Sequence[HistoryTurn],
    ) -> str:
        answered = [
            q for q in persona.questions if coverage.get(q.ref, QuestionCoverage()).answered
        ]
        if not answered:
            return persona.questions[0].ref
        return max(answered, key=lambda q: coverage[q.ref].confidence).ref


_POLICIES: dict[QuestionPolicyKind, QuestionPolicy] = {
    "guided": GuidedPolicy(),
    "adaptive": AdaptivePolicy(),
    "stress": StressPolicy(),
}


def policy_for(kind: QuestionPolicyKind) -> QuestionPolicy:
    try:
        return _POLICIES[kind]
    except KeyError as exc:
        raise ConfigError(f"unknown question policy {kind!r}; known: {sorted(_POLICIES)}") from exc
