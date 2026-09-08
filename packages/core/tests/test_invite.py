from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

from interviewer_core.domain import InterviewInvite


def _invite(**overrides: object) -> InterviewInvite:
    base = {
        "id": "inv1",
        "slug": "abc123",
        "persona_id": "p1",
        "passkey_hash": "$2b$...",
        "expires_at": datetime(2026, 1, 8, tzinfo=UTC),
        "max_sessions": 1,
        "used_count": 0,
        "status": "active",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return InterviewInvite(**base)  # type: ignore[arg-type]


def test_claimable_when_active_unexpired_and_open() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    result = _invite().is_claimable(now)
    assert result.claimable is True
    assert result.reason is None


def test_expired_names_the_reason() -> None:
    now = datetime(2026, 1, 9, tzinfo=UTC)
    result = _invite().is_claimable(now)
    assert not result.claimable and result.reason == "expired"


def test_retired_names_the_reason() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    result = _invite(status="retired").is_claimable(now)
    assert not result.claimable and result.reason == "retired"


def test_exhausted_names_the_reason() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    result = _invite(used_count=1, max_sessions=1).is_claimable(now)
    assert not result.claimable and result.reason == "exhausted"


def test_no_field_can_hold_a_plaintext_passkey() -> None:
    field_names = {f.name for f in fields(InterviewInvite)}
    assert "passkey" not in field_names
    assert "plaintext_passkey" not in field_names


def test_repr_never_carries_a_plaintext_passkey() -> None:
    invite = _invite()
    assert "passkey_hash" in repr(invite)
    # the hash is allowed in repr; there is simply no other field to leak
    assert repr(invite).count("passkey") == 1
