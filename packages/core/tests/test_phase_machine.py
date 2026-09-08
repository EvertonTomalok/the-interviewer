from __future__ import annotations

from datetime import UTC, datetime

import pytest

from interviewer_core.domain import Session, advance
from interviewer_core.errors import DomainError


def _session(phase: str) -> Session:
    return Session(
        id="s1",
        invite_id="inv1",
        persona_id="p1",
        phase=phase,  # type: ignore[arg-type]
        candidate_name=None,
        name_confidence=None,
        coverage={},
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_intake_to_questioning_on_register_name() -> None:
    session = advance(_session("intake"), "register_name")
    assert session.phase == "questioning"


def test_questioning_can_record_answer_and_stay() -> None:
    session = advance(_session("questioning"), "record_answer")
    assert session.phase == "questioning"


def test_questioning_to_closing_on_reach_closing() -> None:
    session = advance(_session("questioning"), "reach_closing")
    assert session.phase == "closing"


def test_closing_to_evaluating_to_completed() -> None:
    session = advance(_session("closing"), "start_evaluation")
    assert session.phase == "evaluating"
    session = advance(session, "complete")
    assert session.phase == "completed"


def test_evaluating_can_fail() -> None:
    session = advance(_session("evaluating"), "fail")
    assert session.phase == "failed"


def test_intake_or_questioning_can_abandon() -> None:
    assert advance(_session("intake"), "abandon").phase == "abandoned"
    assert advance(_session("questioning"), "abandon").phase == "abandoned"


def test_an_answer_in_closing_is_illegal() -> None:
    with pytest.raises(DomainError, match="record_answer"):
        advance(_session("closing"), "record_answer")


def test_a_second_intake_after_the_name_landed_is_illegal() -> None:
    session = advance(_session("intake"), "register_name")
    with pytest.raises(DomainError, match="register_name"):
        advance(session, "register_name")


def test_created_has_no_outgoing_transition() -> None:
    with pytest.raises(DomainError):
        advance(_session("created"), "register_name")
