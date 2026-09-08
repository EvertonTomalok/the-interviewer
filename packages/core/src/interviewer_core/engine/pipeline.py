"""`TurnPipeline`: one candidate turn, `route -> compose -> guard`.

Each stage can end the chain early, with a reason: `route` ends it for a
closing turn (no model call at all -- the farewell is authored text) and for
an intake re-ask; only when it instead resolves *which* question comes next
does `compose` run, and only after `compose` does the expensive-to-skip
`guard` stage run. That ordering -- decide first, generate second, check
third -- is the point of the chain, not an accident.
"""

from __future__ import annotations

from dataclasses import replace

from interviewer_core.domain.entities import Persona, PersonaQuestion, Session
from interviewer_core.domain.phase import advance
from interviewer_core.engine.coverage import (
    assess_answer,
    completion_reason,
    mark_answered,
    mark_asked,
    question_numbers,
)
from interviewer_core.engine.guardrails import amendment_for, check_question
from interviewer_core.engine.policies import policy_for
from interviewer_core.engine.prompting import (
    build_intake_messages,
    build_question_messages,
    extract_json,
)
from interviewer_core.engine.types import HistoryTurn, TurnOutcome, TurnRequest
from interviewer_core.ports.llm import LLMAnswer, LLMMessage, LLMPort, LLMUsage

_EXTRACTED_NAME_CONFIDENCE = 1.0
_FALLBACK_NAME_CONFIDENCE = 0.0
_INTAKE_ATTEMPTS_BEFORE_FALLBACK = 2
_NO_USAGE = LLMUsage(prompt_tokens=0, completion_tokens=0)


def _question_by_ref(persona: Persona, ref: str) -> PersonaQuestion:
    return next(q for q in persona.questions if q.ref == ref)


def _sum_usage(*usages: LLMUsage) -> LLMUsage:
    return LLMUsage(
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
    )


class TurnPipeline:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def run(self, request: TurnRequest) -> TurnOutcome:
        if request.session.phase == "intake":
            return await self._run_intake(request)
        return await self._run_questioning(request)

    # -- route --------------------------------------------------------

    async def _extract_name(
        self, persona: Persona, candidate_text: str
    ) -> tuple[str | None, LLMUsage]:
        answer = await self._llm.complete(
            build_intake_messages(persona, candidate_text), temperature=0.0, max_tokens=60
        )
        data = extract_json(answer.text)
        name = data.get("name") if isinstance(data, dict) else None
        return (name.strip() if isinstance(name, str) and name.strip() else None), answer.usage

    async def _run_intake(self, request: TurnRequest) -> TurnOutcome:
        attempt = sum(1 for h in request.history if h.kind == "intake") + 1
        name, usage = await self._extract_name(request.persona, request.candidate_text)

        if name is None and attempt < _INTAKE_ATTEMPTS_BEFORE_FALLBACK:
            return TurnOutcome(
                session=request.session,
                text=request.persona.intake_prompt_text,
                kind="intake",
                question_ref=None,
                ends_session=False,
                end_reason=None,
                degraded=False,
                question_number=None,
                question_total=None,
                usage=usage,
            )

        if name is not None:
            candidate_name, confidence = name, _EXTRACTED_NAME_CONFIDENCE
        else:
            candidate_name, confidence = request.candidate_text.strip(), _FALLBACK_NAME_CONFIDENCE

        session = replace(
            advance(request.session, "register_name"),
            candidate_name=candidate_name,
            name_confidence=confidence,
        )
        first_ref = policy_for(request.persona.policy).pick_next(
            request.persona, session.coverage, request.history
        )
        return await self._ask(
            request, session, _question_by_ref(request.persona, first_ref), usage
        )

    async def _run_questioning(self, request: TurnRequest) -> TurnOutcome:
        """No `LLMPort` call happens before the completion check: whether a
        question fires the closing turn never waits on the model, and a
        closing turn -- farewell text, scripted -- spends nothing at all."""
        last = next(h for h in reversed(request.history) if h.kind == "question")
        assert last.question_ref is not None
        question = _question_by_ref(request.persona, last.question_ref)
        answered, confidence = assess_answer(question, request.candidate_text)

        coverage = mark_answered(
            request.session.coverage, last.question_ref, answered=answered, confidence=confidence
        )
        session = advance(replace(request.session, coverage=coverage), "record_answer")

        reason = completion_reason(request.persona, coverage)
        if reason is not None:
            closed = advance(session, "reach_closing")
            return TurnOutcome(
                session=closed,
                text=request.persona.farewell_text,
                kind="closing",
                question_ref=None,
                ends_session=True,
                end_reason=reason,
                degraded=False,
                question_number=None,
                question_total=None,
                usage=_NO_USAGE,
            )

        next_ref = policy_for(request.persona.policy).pick_next(
            request.persona, coverage, request.history
        )
        return await self._ask(
            request, session, _question_by_ref(request.persona, next_ref), _NO_USAGE
        )

    # -- compose --------------------------------------------------------

    async def _compose(
        self,
        persona: Persona,
        question: PersonaQuestion,
        history: tuple[HistoryTurn, ...],
        *,
        amendment: str = "",
    ) -> LLMAnswer:
        messages: tuple[LLMMessage, ...] = build_question_messages(
            persona, question, history, amendment=amendment
        )
        return await self._llm.complete(
            messages, temperature=persona.temperature, max_tokens=persona.max_tokens
        )

    # -- guard ------------------------------------------------------------

    async def _ask(
        self,
        request: TurnRequest,
        session: Session,
        question: PersonaQuestion,
        prior_usage: LLMUsage,
    ) -> TurnOutcome:
        """compose -> guard, with one regeneration and a scripted fallback."""
        first = await self._compose(request.persona, question, request.history)
        failures = check_question(first.text, question, request.persona, request.history)

        text, degraded, usage = first.text, False, _sum_usage(prior_usage, first.usage)
        if failures:
            second = await self._compose(
                request.persona, question, request.history, amendment=amendment_for(failures)
            )
            usage = _sum_usage(usage, second.usage)
            if not check_question(second.text, question, request.persona, request.history):
                text = second.text
            else:
                text, degraded = question.text, True

        coverage = mark_asked(session.coverage, question.ref)
        session = replace(session, coverage=coverage)
        number, total = question_numbers(request.persona, coverage)
        return TurnOutcome(
            session=session,
            text=text,
            kind="question",
            question_ref=question.ref,
            ends_session=False,
            end_reason=None,
            degraded=degraded,
            question_number=number,
            question_total=total,
            usage=usage,
        )
