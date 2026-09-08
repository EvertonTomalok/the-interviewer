"""Dict-backed twins of the SQL repositories -- same ports, same uniqueness
enforcement. This is what every other lane's unit suite runs on."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from interviewer_core.domain.entities import (
    Area,
    Artifact,
    InterviewInvite,
    InterviewReport,
    Persona,
    Session,
    Turn,
    User,
    WorkflowRun,
)


class DuplicateKeyError(Exception):
    """Raised by an in-memory repository where a unique constraint would fire
    in SQL -- same error shape on both implementations, on purpose."""


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}

    async def add(self, user: User) -> None:
        if any(u.email == user.email for u in self._by_id.values()):
            raise DuplicateKeyError(f"email {user.email!r} already registered")
        self._by_id[user.id] = user

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._by_id.values() if u.email == email), None)


class InMemoryAreaRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Area] = {}

    async def add(self, area: Area) -> None:
        if any(a.slug == area.slug for a in self._by_id.values()):
            raise DuplicateKeyError(f"area slug {area.slug!r} already exists")
        self._by_id[area.id] = area

    async def get(self, area_id: str) -> Area | None:
        return self._by_id.get(area_id)

    async def list(self) -> Sequence[Area]:
        return list(self._by_id.values())


class InMemoryPersonaRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Persona] = {}

    async def add(self, persona: Persona) -> None:
        clash = any(
            p.area_id == persona.area_id and p.version == persona.version
            for p in self._by_id.values()
        )
        if clash:
            raise DuplicateKeyError(
                f"persona area {persona.area_id!r} version {persona.version!r} already exists"
            )
        self._by_id[persona.id] = persona

    async def get(self, persona_id: str) -> Persona | None:
        return self._by_id.get(persona_id)

    async def latest_published(self, area_id: str) -> Persona | None:
        candidates = [
            p for p in self._by_id.values() if p.area_id == area_id and p.status == "published"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.version)


class InMemoryInviteRepository:
    def __init__(self) -> None:
        self._by_slug: dict[str, InterviewInvite] = {}
        self._lock = asyncio.Lock()

    async def add(self, invite: InterviewInvite) -> None:
        if invite.slug in self._by_slug:
            raise DuplicateKeyError(f"invite slug {invite.slug!r} already exists")
        self._by_slug[invite.slug] = invite

    async def get_by_slug(self, slug: str) -> InterviewInvite | None:
        return self._by_slug.get(slug)

    async def claim(self, slug: str, now: datetime) -> InterviewInvite | None:
        async with self._lock:
            invite = self._by_slug.get(slug)
            if invite is None:
                return None
            claimability = invite.is_claimable(now)
            if not claimability.claimable:
                return None
            claimed = replace(invite, used_count=invite.used_count + 1)
            self._by_slug[slug] = claimed
            return claimed

    async def delete(self, invite_id: str) -> None:
        for slug, invite in list(self._by_slug.items()):
            if invite.id == invite_id:
                del self._by_slug[slug]


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Session] = {}

    async def add(self, session: Session) -> None:
        self._by_id[session.id] = session

    async def get(self, session_id: str) -> Session | None:
        return self._by_id.get(session_id)

    async def update(self, session: Session) -> None:
        if session.id not in self._by_id:
            raise LookupError(f"no session {session.id!r} to update")
        self._by_id[session.id] = session


class InMemoryTurnRepository:
    def __init__(self) -> None:
        self._by_session: dict[str, dict[int, Turn]] = {}

    async def add(self, turn: Turn) -> None:
        by_index = self._by_session.setdefault(turn.session_id, {})
        if turn.index in by_index:
            raise DuplicateKeyError(
                f"turn already exists at session {turn.session_id!r} index {turn.index!r}"
            )
        by_index[turn.index] = turn

    async def list_for_session(self, session_id: str) -> Sequence[Turn]:
        by_index = self._by_session.get(session_id, {})
        return [by_index[i] for i in sorted(by_index)]


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Artifact] = {}

    async def add(self, artifact: Artifact) -> None:
        self._by_id[artifact.id] = artifact

    async def get(self, artifact_id: str) -> Artifact | None:
        return self._by_id.get(artifact_id)


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._by_session: dict[str, InterviewReport] = {}

    async def add(self, report: InterviewReport) -> None:
        self._by_session[report.session_id] = report

    async def get_for_session(self, session_id: str) -> InterviewReport | None:
        return self._by_session.get(session_id)


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, WorkflowRun] = {}
        self._by_key: dict[str, str] = {}

    async def add(self, run: WorkflowRun) -> None:
        if run.idempotency_key in self._by_key:
            raise DuplicateKeyError(
                f"workflow run with idempotency key {run.idempotency_key!r} already exists"
            )
        self._by_id[run.id] = run
        self._by_key[run.idempotency_key] = run.id

    async def get(self, run_id: str) -> WorkflowRun | None:
        return self._by_id.get(run_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        run_id = self._by_key.get(idempotency_key)
        return self._by_id.get(run_id) if run_id else None

    async def update(self, run: WorkflowRun) -> None:
        if run.id not in self._by_id:
            raise LookupError(f"no workflow run {run.id!r} to update")
        self._by_id[run.id] = run
