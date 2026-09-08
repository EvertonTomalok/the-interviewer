"""The SQL half of the shared contract suite. Needs a real Postgres --
`make itest`, never `make check`."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from . import _shared
from ._shared import Repos

pytestmark = pytest.mark.integration


async def test_persona_versioning_and_round_trip(sql_repos: Repos) -> None:
    await _shared.assert_persona_versioning_and_round_trip(sql_repos, IntegrityError)


async def test_turn_ordering_and_uniqueness(sql_repos: Repos) -> None:
    await _shared.assert_turn_ordering_and_uniqueness(sql_repos, IntegrityError)


async def test_session_round_trip_and_phase_persists(sql_repos: Repos) -> None:
    await _shared.assert_session_round_trip_and_phase_persists(sql_repos)


async def test_invite_claim_reasons(sql_repos: Repos) -> None:
    await _shared.assert_invite_claim_reasons(sql_repos)


async def test_invite_claim_under_contention(sql_repos: Repos) -> None:
    async def factory() -> Repos:
        return sql_repos

    await _shared.assert_invite_claim_under_contention(factory)


async def test_report_upsert_on_session(sql_repos: Repos) -> None:
    await _shared.assert_report_upsert_on_session(sql_repos, IntegrityError)


async def test_run_idempotency_key_is_unique(sql_repos: Repos) -> None:
    await _shared.assert_run_idempotency_key_is_unique(sql_repos, IntegrityError)


async def test_absent_ids_return_none(sql_repos: Repos) -> None:
    await _shared.assert_absent_ids_return_none(sql_repos)
