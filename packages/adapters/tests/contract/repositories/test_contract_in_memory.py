"""The in-memory half of the shared contract suite. Part of `make check` --
no network, no container."""

from __future__ import annotations

import pytest

from interviewer_adapters.persistence.in_memory import (
    DuplicateKeyError,
    InMemoryInviteRepository,
    InMemoryPersonaRepository,
    InMemoryReportRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTurnRepository,
)

from . import _shared
from ._shared import Repos


async def _repos() -> Repos:
    return Repos(
        persona=InMemoryPersonaRepository(),
        invite=InMemoryInviteRepository(),
        session=InMemorySessionRepository(),
        turn=InMemoryTurnRepository(),
        report=InMemoryReportRepository(),
        run=InMemoryRunRepository(),
    )


@pytest.fixture
async def repos() -> Repos:
    return await _repos()


async def test_persona_versioning_and_round_trip(repos: Repos) -> None:
    await _shared.assert_persona_versioning_and_round_trip(repos, DuplicateKeyError)


async def test_turn_ordering_and_uniqueness(repos: Repos) -> None:
    await _shared.assert_turn_ordering_and_uniqueness(repos, DuplicateKeyError)


async def test_session_round_trip_and_phase_persists(repos: Repos) -> None:
    await _shared.assert_session_round_trip_and_phase_persists(repos)


async def test_invite_claim_reasons(repos: Repos) -> None:
    await _shared.assert_invite_claim_reasons(repos)


async def test_invite_claim_under_contention() -> None:
    await _shared.assert_invite_claim_under_contention(_repos)


async def test_report_upsert_on_session(repos: Repos) -> None:
    await _shared.assert_report_upsert_on_session(repos, DuplicateKeyError)


async def test_run_idempotency_key_is_unique(repos: Repos) -> None:
    await _shared.assert_run_idempotency_key_is_unique(repos, DuplicateKeyError)


async def test_absent_ids_return_none(repos: Repos) -> None:
    await _shared.assert_absent_ids_return_none(repos)
