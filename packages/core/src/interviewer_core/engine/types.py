"""The engine's own request/response shapes.

These are deliberately not `Turn`/`Session` rows: the engine is a pure
function of "what has been said so far" and does not know how the workflow
(T07) persists a round. `HistoryTurn` is what the engine itself hands back
each call, so a caller accumulates history by echoing a `TurnOutcome` plus
the candidate's next reply -- no separate read model to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from interviewer_core.domain.entities import Persona, Session, TurnKind
from interviewer_core.ports.llm import LLMUsage

EndReason = Literal["min_coverage", "max_questions"]


@dataclass(frozen=True)
class HistoryTurn:
    """One completed round, as the engine itself produced and then heard back."""

    kind: TurnKind
    question_ref: str | None
    asked_text: str
    candidate_text: str


@dataclass(frozen=True)
class TurnRequest:
    """One call into the pipeline: the pinned persona, the session as of the
    last completed round, every round since, and what the candidate just said."""

    persona: Persona
    session: Session
    history: tuple[HistoryTurn, ...]
    candidate_text: str


@dataclass(frozen=True)
class TurnOutcome:
    """What the pipeline decided. `session` is the new state to persist."""

    session: Session
    text: str
    kind: TurnKind
    question_ref: str | None
    ends_session: bool
    end_reason: EndReason | None
    degraded: bool
    question_number: int | None
    question_total: int | None
    usage: LLMUsage
