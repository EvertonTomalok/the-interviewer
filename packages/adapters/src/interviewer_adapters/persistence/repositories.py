"""SQL repository adapters. Every method returns a frozen domain dataclass --
no `SQLModel` instance ever leaves this module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlmodel import col

from interviewer_adapters.persistence.session import SessionFactory
from interviewer_adapters.persistence.tables import (
    AreaTable,
    ArtifactTable,
    InterviewInviteTable,
    InterviewReportTable,
    PersonaTable,
    SessionTable,
    TurnTable,
    UserTable,
    WorkflowRunTable,
)
from interviewer_core.domain.entities import (
    Area,
    Artifact,
    InterviewInvite,
    InterviewReport,
    Persona,
    PersonaQuestion,
    QuestionCoverage,
    QuestionScore,
    Session,
    Turn,
    User,
    WorkflowRun,
)

# --- converters ------------------------------------------------------------


def _user_to_domain(row: UserTable) -> User:
    return User(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        role=row.role,  # type: ignore[arg-type]
        created_at=row.created_at,
    )


def _area_to_domain(row: AreaTable) -> Area:
    return Area(id=row.id, slug=row.slug, name=row.name, description=row.description)


def _persona_to_domain(row: PersonaTable) -> Persona:
    return Persona(
        id=row.id,
        area_id=row.area_id,
        name=row.name,
        version=row.version,
        status=row.status,  # type: ignore[arg-type]
        language=row.language,
        voice=row.voice,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        timeout_seconds=row.timeout_seconds,
        greeting_text=row.greeting_text,
        intake_prompt_text=row.intake_prompt_text,
        farewell_text=row.farewell_text,
        questions=tuple(PersonaQuestion(**q) for q in row.questions_json),
        policy=row.policy,  # type: ignore[arg-type]
        min_coverage=row.min_coverage,
        max_questions=row.max_questions,
        rubric=row.rubric,
        created_at=row.created_at,
    )


def _persona_to_row(persona: Persona) -> PersonaTable:
    return PersonaTable(
        id=persona.id,
        area_id=persona.area_id,
        name=persona.name,
        version=persona.version,
        status=persona.status,
        language=persona.language,
        voice=persona.voice,
        llm_provider=persona.llm_provider,
        llm_model=persona.llm_model,
        temperature=persona.temperature,
        max_tokens=persona.max_tokens,
        timeout_seconds=persona.timeout_seconds,
        greeting_text=persona.greeting_text,
        intake_prompt_text=persona.intake_prompt_text,
        farewell_text=persona.farewell_text,
        questions_json=[vars(q) for q in persona.questions],
        policy=persona.policy,
        min_coverage=persona.min_coverage,
        max_questions=persona.max_questions,
        rubric=persona.rubric,
        created_at=persona.created_at,
    )


def _invite_to_domain(row: InterviewInviteTable) -> InterviewInvite:
    return InterviewInvite(
        id=row.id,
        slug=row.slug,
        persona_id=row.persona_id,
        passkey_hash=row.passkey_hash,
        expires_at=row.expires_at,
        max_sessions=row.max_sessions,
        used_count=row.used_count,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
    )


def _session_to_domain(row: SessionTable) -> Session:
    return Session(
        id=row.id,
        invite_id=row.invite_id,
        persona_id=row.persona_id,
        phase=row.phase,  # type: ignore[arg-type]
        candidate_name=row.candidate_name,
        name_confidence=row.name_confidence,
        coverage={k: QuestionCoverage(**v) for k, v in row.coverage_json.items()},
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


def _turn_to_domain(row: TurnTable) -> Turn:
    return Turn(
        id=row.id,
        session_id=row.session_id,
        index=row.index,
        kind=row.kind,  # type: ignore[arg-type]
        question_ref=row.question_ref,
        transcript=row.transcript,
        audio_artifact_id=row.audio_artifact_id,
        usage=row.usage_json,
        created_at=row.created_at,
    )


def _artifact_to_domain(row: ArtifactTable) -> Artifact:
    return Artifact(
        id=row.id,
        session_id=row.session_id,
        kind=row.kind,
        mime=row.mime,
        size_bytes=row.size_bytes,
        uri=row.uri,
        checksum=row.checksum,
        created_at=row.created_at,
    )


def _report_to_domain(row: InterviewReportTable) -> InterviewReport:
    return InterviewReport(
        id=row.id,
        session_id=row.session_id,
        persona_id=row.persona_id,
        scores=tuple(QuestionScore(**s) for s in row.scores_json),
        overall_score=row.overall_score,
        summary=row.summary,
        created_at=row.created_at,
    )


def _run_to_domain(row: WorkflowRunTable) -> WorkflowRun:
    return WorkflowRun(
        id=row.id,
        workflow=row.workflow,
        idempotency_key=row.idempotency_key,
        status=row.status,  # type: ignore[arg-type]
        input=row.input_json,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- repositories ------------------------------------------------------------


class SqlUserRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, user: User) -> None:
        row = UserTable(
            id=user.id,
            email=user.email,
            password_hash=user.password_hash,
            role=user.role,
            created_at=user.created_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def get_by_email(self, email: str) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(select(UserTable).where(col(UserTable.email) == email))
            row = result.scalar_one_or_none()
            return _user_to_domain(row) if row else None


class SqlAreaRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, area: Area) -> None:
        row = AreaTable(id=area.id, slug=area.slug, name=area.name, description=area.description)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def get(self, area_id: str) -> Area | None:
        async with self._session_factory() as session:
            row = await session.get(AreaTable, area_id)
            return _area_to_domain(row) if row else None

    async def list(self) -> Sequence[Area]:
        async with self._session_factory() as session:
            result = await session.execute(select(AreaTable))
            return [_area_to_domain(r) for r in result.scalars().all()]


class SqlPersonaRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, persona: Persona) -> None:
        async with self._session_factory() as session:
            session.add(_persona_to_row(persona))
            await session.commit()

    async def get(self, persona_id: str) -> Persona | None:
        async with self._session_factory() as session:
            row = await session.get(PersonaTable, persona_id)
            return _persona_to_domain(row) if row else None

    async def latest_published(self, area_id: str) -> Persona | None:
        async with self._session_factory() as session:
            stmt = (
                select(PersonaTable)
                .where(col(PersonaTable.area_id) == area_id)
                .where(col(PersonaTable.status) == "published")
                .order_by(col(PersonaTable.version).desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _persona_to_domain(row) if row else None


class SqlInviteRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, invite: InterviewInvite) -> None:
        row = InterviewInviteTable(
            id=invite.id,
            slug=invite.slug,
            persona_id=invite.persona_id,
            passkey_hash=invite.passkey_hash,
            expires_at=invite.expires_at,
            max_sessions=invite.max_sessions,
            used_count=invite.used_count,
            status=invite.status,
            created_at=invite.created_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def get_by_slug(self, slug: str) -> InterviewInvite | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(InterviewInviteTable).where(col(InterviewInviteTable.slug) == slug)
            )
            row = result.scalar_one_or_none()
            return _invite_to_domain(row) if row else None

    async def claim(self, slug: str, now: datetime) -> InterviewInvite | None:
        table = InterviewInviteTable.__table__  # type: ignore[attr-defined]
        stmt = (
            sa_update(table)
            .where(table.c.slug == slug)
            .where(table.c.status == "active")
            .where(table.c.expires_at > now)
            .where(table.c.used_count < table.c.max_sessions)
            .values(used_count=table.c.used_count + 1)
            .returning(table)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            mapping = result.mappings().one_or_none()
            await session.commit()
            if mapping is None:
                return None
            return _invite_to_domain(InterviewInviteTable(**dict(mapping)))

    async def delete(self, invite_id: str) -> None:
        async with self._session_factory() as session:
            row = await session.get(InterviewInviteTable, invite_id)
            if row is not None:
                await session.delete(row)
                await session.commit()


class SqlSessionRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, session_obj: Session) -> None:
        row = SessionTable(
            id=session_obj.id,
            invite_id=session_obj.invite_id,
            persona_id=session_obj.persona_id,
            phase=session_obj.phase,
            candidate_name=session_obj.candidate_name,
            name_confidence=session_obj.name_confidence,
            coverage_json={k: vars(v) for k, v in session_obj.coverage.items()},
            started_at=session_obj.started_at,
            ended_at=session_obj.ended_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def get(self, session_id: str) -> Session | None:
        async with self._session_factory() as session:
            row = await session.get(SessionTable, session_id)
            return _session_to_domain(row) if row else None

    async def update(self, session_obj: Session) -> None:
        async with self._session_factory() as session:
            row = await session.get(SessionTable, session_obj.id)
            if row is None:
                raise LookupError(f"no session {session_obj.id!r} to update")
            row.phase = session_obj.phase
            row.candidate_name = session_obj.candidate_name
            row.name_confidence = session_obj.name_confidence
            row.coverage_json = {k: vars(v) for k, v in session_obj.coverage.items()}
            row.ended_at = session_obj.ended_at
            session.add(row)
            await session.commit()

    async def list_all(self) -> Sequence[Session]:
        async with self._session_factory() as session:
            stmt = select(SessionTable).order_by(col(SessionTable.started_at).desc())
            result = await session.execute(stmt)
            return [_session_to_domain(r) for r in result.scalars().all()]


class SqlTurnRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, turn: Turn) -> None:
        row = TurnTable(
            id=turn.id,
            session_id=turn.session_id,
            index=turn.index,
            kind=turn.kind,
            question_ref=turn.question_ref,
            transcript=turn.transcript,
            audio_artifact_id=turn.audio_artifact_id,
            usage_json=dict(turn.usage),
            created_at=turn.created_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_for_session(self, session_id: str) -> Sequence[Turn]:
        async with self._session_factory() as session:
            stmt = (
                select(TurnTable)
                .where(col(TurnTable.session_id) == session_id)
                .order_by(col(TurnTable.index))
            )
            result = await session.execute(stmt)
            return [_turn_to_domain(r) for r in result.scalars().all()]


class SqlArtifactRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, artifact: Artifact) -> None:
        row = ArtifactTable(
            id=artifact.id,
            session_id=artifact.session_id,
            kind=artifact.kind,
            mime=artifact.mime,
            size_bytes=artifact.size_bytes,
            uri=artifact.uri,
            checksum=artifact.checksum,
            created_at=artifact.created_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def get(self, artifact_id: str) -> Artifact | None:
        async with self._session_factory() as session:
            row = await session.get(ArtifactTable, artifact_id)
            return _artifact_to_domain(row) if row else None


class SqlReportRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, report: InterviewReport) -> None:
        row = InterviewReportTable(
            id=report.id,
            session_id=report.session_id,
            persona_id=report.persona_id,
            scores_json=[vars(s) for s in report.scores],
            overall_score=report.overall_score,
            summary=report.summary,
            created_at=report.created_at,
        )
        async with self._session_factory() as session:
            existing = await session.execute(
                select(InterviewReportTable).where(
                    col(InterviewReportTable.session_id) == report.session_id
                )
            )
            found = existing.scalar_one_or_none()
            if found is not None:
                found.scores_json = row.scores_json
                found.overall_score = row.overall_score
                found.summary = row.summary
                session.add(found)
            else:
                session.add(row)
            await session.commit()

    async def get_for_session(self, session_id: str) -> InterviewReport | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(InterviewReportTable).where(
                    col(InterviewReportTable.session_id) == session_id
                )
            )
            row = result.scalar_one_or_none()
            return _report_to_domain(row) if row else None


class SqlRunRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, run: WorkflowRun) -> None:
        row = WorkflowRunTable(
            id=run.id,
            workflow=run.workflow,
            idempotency_key=run.idempotency_key,
            status=run.status,
            input_json=dict(run.input),
            error=run.error,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def get(self, run_id: str) -> WorkflowRun | None:
        async with self._session_factory() as session:
            row = await session.get(WorkflowRunTable, run_id)
            return _run_to_domain(row) if row else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(WorkflowRunTable).where(
                    col(WorkflowRunTable.idempotency_key) == idempotency_key
                )
            )
            row = result.scalar_one_or_none()
            return _run_to_domain(row) if row else None

    async def update(self, run: WorkflowRun) -> None:
        async with self._session_factory() as session:
            row = await session.get(WorkflowRunTable, run.id)
            if row is None:
                raise LookupError(f"no workflow run {run.id!r} to update")
            row.status = run.status
            row.error = run.error
            row.updated_at = run.updated_at
            session.add(row)
            await session.commit()
