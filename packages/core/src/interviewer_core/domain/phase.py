"""The session phase machine (PRD §1, §4).

`created` is the value of a session nobody has persisted yet: the claim
writes the row already in `intake`, so no client ever observes `created`.
It has no outgoing transition here for that reason -- the move into
`intake` is made once, by the code that spends the invite, not by this
function.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from interviewer_core.domain.entities import Session, SessionPhase
from interviewer_core.errors import DomainError

SessionEvent = Literal[
    "register_name",
    "record_answer",
    "reach_closing",
    "start_evaluation",
    "complete",
    "fail",
    "abandon",
]

_TRANSITIONS: dict[SessionPhase, dict[SessionEvent, SessionPhase]] = {
    "intake": {
        "register_name": "questioning",
        "abandon": "abandoned",
    },
    "questioning": {
        "record_answer": "questioning",
        "reach_closing": "closing",
        "abandon": "abandoned",
    },
    "closing": {
        "start_evaluation": "evaluating",
    },
    "evaluating": {
        "complete": "completed",
        "fail": "failed",
    },
}


def advance(session: Session, event: SessionEvent) -> Session:
    """Return a new session moved by `event`, or raise `DomainError`."""
    allowed = _TRANSITIONS.get(session.phase, {})
    if event not in allowed:
        raise DomainError(f"cannot apply event {event!r} to a session in phase {session.phase!r}")
    return replace(session, phase=allowed[event])
