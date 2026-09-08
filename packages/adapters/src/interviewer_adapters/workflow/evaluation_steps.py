"""The evaluation workflow (PRD §5.5), three steps: `collect_answers ->
score -> commit_report`. Same engine, same template, same guarantees as the
turn workflow -- it is registered beside it, not special-cased.

The caller (T09) starts this workflow with
`idempotency_key=f"{session_id}:report"`, so pressing **Finish** twice joins
the existing run instead of scoring twice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from interviewer_adapters.workflow.base import BaseStep
from interviewer_adapters.workflow.turn_steps import build_history
from interviewer_core.domain.entities import InterviewReport, QuestionScore
from interviewer_core.domain.phase import advance
from interviewer_core.engine import HistoryTurn, evaluate
from interviewer_core.ports.clock import Clock
from interviewer_core.ports.ids import IdGenerator
from interviewer_core.ports.llm import LLMPort
from interviewer_core.ports.repositories import (
    PersonaRepository,
    ReportRepository,
    SessionRepository,
    TurnRepository,
)
from interviewer_core.ports.workflow import StepContext


class CollectAnswersStep(BaseStep):
    """Reads only `kind="question"` turns -- the intake name is context on
    the report, never a scored answer, and the farewell is not an answer
    at all."""

    name = "collect_answers"
    max_attempts = 3

    def __init__(self, *, turns: TurnRepository) -> None:
        self._turns = turns

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        session_id = str(ctx.input["session_id"])
        all_turns = await self._turns.list_for_session(session_id)
        history = [h for h in build_history(all_turns) if h.kind == "question"]
        return {
            "history": [
                {
                    "kind": h.kind,
                    "question_ref": h.question_ref,
                    "asked_text": h.asked_text,
                    "candidate_text": h.candidate_text,
                }
                for h in history
            ]
        }


class ScoreStep(BaseStep):
    """The expensive one: one model call over every question <-> answer
    pair. Checkpointed like any other step, so a crash during
    `commit_report` replays without paying for scoring twice."""

    name = "score"
    max_attempts = 3

    def __init__(
        self, *, llm: LLMPort, personas: PersonaRepository, clock: Clock, ids: IdGenerator
    ) -> None:
        self._llm = llm
        self._personas = personas
        self._clock = clock
        self._ids = ids

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        persona = await self._personas.get(str(ctx.input["persona_id"]))
        if persona is None:
            raise LookupError(f"no persona {ctx.input['persona_id']!r}")

        history = tuple(
            HistoryTurn(
                kind=h["kind"],
                question_ref=h["question_ref"],
                asked_text=h["asked_text"],
                candidate_text=h["candidate_text"],
            )
            for h in ctx.outputs["collect_answers"]["history"]
        )
        report = await evaluate(
            session_id=str(ctx.input["session_id"]),
            persona=persona,
            history=history,
            llm=self._llm,
            clock=self._clock,
            ids=self._ids,
        )
        return {
            "report_id": report.id,
            "scores": [
                {
                    "question_ref": s.question_ref,
                    "score": s.score,
                    "verdict": s.verdict,
                    "rationale": s.rationale,
                }
                for s in report.scores
            ],
            "overall_score": report.overall_score,
            "summary": report.summary,
        }


class CommitReportStep(BaseStep):
    """Upserts on `session_id` and moves the session to `completed` --
    the report and the phase transition land together, or not at all."""

    name = "commit_report"
    max_attempts = 3

    def __init__(
        self, *, reports: ReportRepository, sessions: SessionRepository, clock: Clock
    ) -> None:
        self._reports = reports
        self._sessions = sessions
        self._clock = clock

    async def run(self, ctx: StepContext) -> Mapping[str, Any]:
        session = await self._sessions.get(str(ctx.input["session_id"]))
        if session is None:
            raise LookupError(f"no session {ctx.input['session_id']!r}")

        scored = ctx.outputs["score"]
        report = InterviewReport(
            id=str(scored["report_id"]),
            session_id=session.id,
            persona_id=str(ctx.input["persona_id"]),
            scores=tuple(
                QuestionScore(
                    question_ref=s["question_ref"],
                    score=s["score"],
                    verdict=s["verdict"],
                    rationale=s["rationale"],
                )
                for s in scored["scores"]
            ),
            overall_score=float(scored["overall_score"]),
            summary=str(scored["summary"]),
            created_at=self._clock.now(),
        )
        await self._reports.add(report)

        completed = replace(advance(session, "complete"), ended_at=self._clock.now())
        await self._sessions.update(completed)

        return {"report_id": report.id}


def build_evaluation_steps(
    *,
    llm: LLMPort,
    personas: PersonaRepository,
    sessions: SessionRepository,
    turns: TurnRepository,
    reports: ReportRepository,
    clock: Clock,
    ids: IdGenerator,
) -> tuple[BaseStep, ...]:
    return (
        CollectAnswersStep(turns=turns),
        ScoreStep(llm=llm, personas=personas, clock=clock, ids=ids),
        CommitReportStep(reports=reports, sessions=sessions, clock=clock),
    )
