"""The evaluator (PRD §5.5): scores a finished transcript against the
pinned persona's `expected_answer` and `rubric` -- never against the
model's own taste, and never averaged by the model either.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from interviewer_core.domain.entities import InterviewReport, Persona, QuestionScore
from interviewer_core.engine.prompting import build_evaluator_messages, extract_json
from interviewer_core.engine.types import HistoryTurn
from interviewer_core.errors import DomainError
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.llm import LLMPort

#: `QuestionScore.verdict` is a plain `str` on the entity (T02); this is the
#: closed vocabulary the engine actually enforces.
_VERDICTS: Final[frozenset[str]] = frozenset({"strong", "adequate", "weak", "not_answered"})

_NOT_ANSWERED_RATIONALE = "the interview ended before this question was reached"


def _answers_by_ref(history: Sequence[HistoryTurn]) -> dict[str, str]:
    return {
        h.question_ref: h.candidate_text for h in history if h.kind == "question" and h.question_ref
    }


def _parse_scores(
    payload: object, persona: Persona, answered: dict[str, str]
) -> tuple[QuestionScore, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("scores"), list):
        raise DomainError("evaluator response is missing a 'scores' array")

    known_refs = {q.ref for q in persona.questions}
    by_ref: dict[str, QuestionScore] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict):
            raise DomainError("evaluator returned a non-object score entry")
        ref = item.get("ref")
        if ref not in known_refs:
            raise DomainError(f"evaluator scored unknown question ref {ref!r}")
        verdict = item.get("verdict")
        if verdict not in _VERDICTS:
            raise DomainError(
                f"evaluator returned verdict {verdict!r}, expected one of {sorted(_VERDICTS)}"
            )
        rationale = item.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise DomainError(f"evaluator score for {ref!r} is missing a rationale")
        score = item.get("score")
        if not isinstance(score, int | float):
            raise DomainError(f"evaluator score for {ref!r} is not numeric")
        by_ref[ref] = QuestionScore(
            question_ref=ref,
            score=max(0.0, min(1.0, float(score))),
            verdict=verdict,
            rationale=rationale.strip(),
        )

    scores: list[QuestionScore] = []
    for q in persona.questions:
        if q.ref not in answered:
            scores.append(
                QuestionScore(
                    question_ref=q.ref,
                    score=0.0,
                    verdict="not_answered",
                    rationale=_NOT_ANSWERED_RATIONALE,
                )
            )
            continue
        if q.ref not in by_ref:
            raise DomainError(f"evaluator did not score {q.ref!r}, which the candidate answered")
        scores.append(by_ref[q.ref])
    return tuple(scores)


def _weighted_mean(scores: Sequence[QuestionScore], persona: Persona) -> float:
    by_ref = {s.question_ref: s for s in scores}
    total_weight = sum(q.weight for q in persona.questions)
    if total_weight <= 0:
        return 0.0
    return sum(by_ref[q.ref].score * q.weight for q in persona.questions) / total_weight


async def evaluate(
    *,
    session_id: str,
    persona: Persona,
    history: Sequence[HistoryTurn],
    llm: LLMPort,
    clock: Clock,
    ids: IdGenerator,
) -> InterviewReport:
    """Score `history` against `persona`'s pinned questions and rubric.

    Pure but for the one `LLMPort.complete` call: the intake and closing
    turns never reach here -- only `kind == "question"` rounds do -- and the
    weighted mean is computed here, in code, never asked of the model.
    """
    answered = _answers_by_ref(history)
    messages = build_evaluator_messages(persona, answered)
    answer = await llm.complete(messages, temperature=0.0, max_tokens=persona.max_tokens)
    payload = extract_json(answer.text)
    scores = _parse_scores(payload, persona, answered)
    overall = _weighted_mean(scores, persona)
    answered_count = sum(1 for s in scores if s.verdict != "not_answered")
    summary = f"{answered_count}/{len(scores)} questions answered; overall score {overall:.2f}."
    return InterviewReport(
        id=ids.new_id(),
        session_id=session_id,
        persona_id=persona.id,
        scores=scores,
        overall_score=overall,
        summary=summary,
        created_at=clock.now(),
    )
